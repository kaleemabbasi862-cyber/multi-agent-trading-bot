import datetime
import os
import json
import logging
import threading
import time
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
import requests
from app.config import settings
from app.database.db import db

logger = logging.getLogger("TradeTalk.EconomicCalendar")

# Pre-event lockout in minutes by impact tier
PRE_EVENT_LOCKOUT_MINUTES = {
    "EXTREME": 30,
    "HIGH": 20,
    "MEDIUM": 10,
    "LOW": 0
}

# Post-event cooldown in minutes by impact tier
POST_EVENT_COOLDOWN_MINUTES = {
    "EXTREME": 15,
    "HIGH": 10,
    "MEDIUM": 5,
    "LOW": 0
}

# Baseline normal spreads for assets to guard against post-news widening
BASELINE_SPREADS = {
    "XAUUSD": 0.35,
    "GOLD": 0.35,
    "EURUSD": 0.00015,
    "GBPUSD": 0.00020,
    "USDJPY": 0.015,
    "USDCAD": 0.00020,
    "AUDUSD": 0.00020,
}

SPREAD_TOLERANCE_MULTIPLIER = 1.5

PRIMARY_CALENDAR_JSON = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
PRIMARY_CALENDAR_XML = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
SECONDARY_CALENDAR_XML = "https://nfs.faireconomy.media/ff_calendar_nextweek.xml"


class EconomicCalendarService:
    """
    Manages real-time macroeconomic calendar tracking, live event scheduling,
    and dynamic high-impact protection lockout windows.
    Enforces Rule 6 (Pre-event Blackout) and Rule 7 (Post-event Cooldown & Spread Normalization).
    """

    def __init__(self):
        self._last_logged_lockout: Optional[str] = None
        self._last_sync_timestamp: float = 0.0
        self._sync_lock = threading.Lock()
        self._initial_sync()

    def seed_mock_schedule(self, base_date: Optional[datetime.datetime] = None) -> List[str]:
        """Test helper to seed simulated events for unit testing."""
        if not base_date:
            base_date = datetime.datetime.now(datetime.timezone.utc)
        event_ids = []
        templates = [
            ("FOMC Interest Rate Decision", "USD", "EXTREME", 18, 0),
            ("US Consumer Price Index (CPI)", "USD", "EXTREME", 12, 30),
            ("US Non-Farm Payrolls (NFP)", "USD", "EXTREME", 12, 30),
        ]
        for name, curr, imp, hr, mn in templates:
            t = base_date.replace(hour=hr, minute=mn, second=0, microsecond=0)
            ev_id = f"TEST_MOCK_{t.strftime('%Y%m%d%H%M')}_{curr}_{imp}"
            db.save_economic_event({
                "id": ev_id,
                "timestamp": t.isoformat(),
                "currency": curr,
                "country": curr[:2],
                "event_name": name,
                "impact": imp,
                "affected_symbols": ["XAUUSD", "EURUSD"]
            })
            event_ids.append(ev_id)
        return event_ids

    def _initial_sync(self):
        """Attempts initial live calendar sync on startup."""
        if os.getenv("TESTING") == "1":
            return
        try:
            threading.Thread(target=self.sync_live_calendar, daemon=True).start()
        except Exception as e:
            logger.error(f"Error starting calendar sync thread: {e}")

    def _parse_xml_feed(self, url: str) -> List[Dict[str, Any]]:
        """Parses ForexFactory XML format."""
        events = []
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TradeTalkAI/2.0"}
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code != 200:
                return []
            root = ET.fromstring(resp.content)
            for ev in root.findall("event"):
                title = ev.findtext("title", "").strip()
                country = ev.findtext("country", "").strip().upper()
                d_str = ev.findtext("date", "").strip()
                t_str = ev.findtext("time", "").strip()
                raw_impact = ev.findtext("impact", "Low").strip()
                forecast = ev.findtext("forecast", "")
                prev = ev.findtext("previous", "")

                if not title or not d_str:
                    continue

                try:
                    if t_str and "day" not in t_str.lower() and "tentative" not in t_str.lower():
                        dt_str = f"{d_str} {t_str}"
                        dt = datetime.datetime.strptime(dt_str, "%m-%d-%Y %I:%M%p")
                    else:
                        dt = datetime.datetime.strptime(d_str, "%m-%d-%Y")
                    # ForexFactory XML publishes US Eastern Time (EDT UTC-4)
                    dt_utc = dt.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=-4))).astimezone(datetime.timezone.utc)
                    utc_iso = dt_utc.isoformat()
                except Exception:
                    continue

                events.append({
                    "title": title,
                    "country": country,
                    "impact": raw_impact,
                    "date_utc": utc_iso,
                    "forecast": forecast,
                    "previous": prev
                })
        except Exception as e:
            logger.warning(f"Error parsing XML feed {url}: {e}")
        return events

    def _parse_json_feed(self, url: str) -> List[Dict[str, Any]]:
        """Parses ForexFactory JSON format."""
        events = []
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TradeTalkAI/2.0"}
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code != 200:
                return []
            raw_list = resp.json()
            if not isinstance(raw_list, list):
                return []
            for item in raw_list:
                title = item.get("title", "").strip()
                country = item.get("country", "").strip().upper()
                date_str = item.get("date", "")
                raw_impact = item.get("impact", "Low").strip()
                forecast = item.get("forecast", "")
                prev = item.get("previous", "")

                if not title or not date_str:
                    continue

                try:
                    ev_dt = datetime.datetime.fromisoformat(date_str)
                    ev_utc = ev_dt.astimezone(datetime.timezone.utc)
                    utc_iso = ev_utc.isoformat()
                except Exception:
                    continue

                events.append({
                    "title": title,
                    "country": country,
                    "impact": raw_impact,
                    "date_utc": utc_iso,
                    "forecast": forecast,
                    "previous": prev
                })
        except Exception as e:
            logger.warning(f"Error parsing JSON feed {url}: {e}")
        return events

    def sync_live_calendar(self, force: bool = False) -> int:
        """
        Fetches live economic calendar events from XML/JSON feeds and stores them in SQLite.
        Caches results for 15 minutes unless force=True.
        """
        now_ts = time.time()
        if not force and (now_ts - self._last_sync_timestamp < 900.0):
            return 0

        with self._sync_lock:
            if not force and (now_ts - self._last_sync_timestamp < 900.0):
                return 0

            # Try XML first (highly reliable), fallback to JSON
            parsed_events = self._parse_xml_feed(PRIMARY_CALENDAR_XML)
            if not parsed_events:
                parsed_events = self._parse_json_feed(PRIMARY_CALENDAR_JSON)

            # Also try next week XML if available
            next_week_events = self._parse_xml_feed(SECONDARY_CALENDAR_XML)
            if next_week_events:
                parsed_events.extend(next_week_events)

            if not parsed_events:
                return 0

            synced_count = 0
            for item in parsed_events:
                title = item["title"]
                country = item["country"]
                raw_impact = item["impact"]
                utc_iso = item["date_utc"]

                title_lower = title.lower()
                is_tier1 = any(k in title_lower for k in [
                    "fomc", "interest rate", "rate decision", "cpi", "consumer price index",
                    "non-farm", "nfp", "unemployment rate", "gdp", "powell"
                ])

                if is_tier1 and country in ["USD", "EUR", "GBP", "JPY"]:
                    impact = "EXTREME"
                elif raw_impact.upper() in ["HIGH", "HOLIDAY"]:
                    impact = "HIGH"
                elif raw_impact.upper() == "MEDIUM":
                    impact = "MEDIUM"
                else:
                    impact = "LOW"

                affected = []
                if country == "USD":
                    affected = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCAD", "AUDUSD"]
                elif country == "EUR":
                    affected = ["EURUSD", "EURGBP", "EURJPY"]
                elif country == "GBP":
                    affected = ["GBPUSD", "EURGBP", "GBPJPY"]
                elif country == "JPY":
                    affected = ["USDJPY", "EURJPY", "GBPJPY"]
                elif country == "AUD":
                    affected = ["AUDUSD"]
                elif country == "CAD":
                    affected = ["USDCAD"]
                else:
                    affected = ["XAUUSD"]

                ev_id = f"LIVE_{utc_iso[:16].replace(':', '').replace('-', '').replace('T', '_')}_{country}_{title[:15].replace(' ', '_').upper()}"

                event_record = {
                    "id": ev_id,
                    "timestamp": utc_iso,
                    "currency": country,
                    "country": country,
                    "event_name": title,
                    "impact": impact,
                    "actual": None,
                    "forecast": item.get("forecast"),
                    "previous": item.get("previous"),
                    "affected_symbols": affected
                }
                db.save_economic_event(event_record)
                synced_count += 1

            self._last_sync_timestamp = time.time()
            if synced_count > 0:
                logger.info(f"Successfully synced {synced_count} live economic events.")
            return synced_count

    def check_lockout_status(
        self,
        symbol: str = "XAUUSD",
        current_spread: Optional[float] = None,
        now: Optional[datetime.datetime] = None,
        include_mock: bool = False
    ) -> Dict[str, Any]:
        """
        Calculates whether trading is locked out due to pre-event blackout or post-event cooldown.
        Also evaluates spread normalization after a high-impact release.
        """
        if now is None:
            now = datetime.datetime.now(datetime.timezone.utc)

        # Trigger background refresh if stale
        if os.getenv("TESTING") != "1" and time.time() - self._last_sync_timestamp > 1800.0:
            threading.Thread(target=self.sync_live_calendar, daemon=True).start()

        # Clean symbol name
        clean_sym = symbol.upper().replace(".PRO", "").replace("_I", "").replace("M", "")
        if "GOLD" in clean_sym or "XAU" in clean_sym:
            clean_sym = "XAUUSD"

        # Fetch recent and upcoming events within a 24-hour window
        window_start = (now - datetime.timedelta(hours=6)).isoformat()
        window_end = (now + datetime.timedelta(hours=18)).isoformat()
        events = db.get_economic_events(start_time=window_start, end_time=window_end, limit=100, include_mock=include_mock)

        is_locked_out = False
        lockout_reason = None
        lockout_type = "NONE"
        active_event = None
        seconds_remaining = 0
        min_to_next = 9999
        min_since_last = 9999
        next_event_name = "None Scheduled"

        # Baseline spread check
        baseline_spread = BASELINE_SPREADS.get(clean_sym, 0.35)
        max_acceptable_post_news_spread = baseline_spread * SPREAD_TOLERANCE_MULTIPLIER

        for ev in events:
            # Check if event affects this symbol
            aff = ev.get("affected_symbols", [])
            if isinstance(aff, str):
                try:
                    aff = json.loads(aff)
                except Exception:
                    aff = [aff]

            aff_upper = [str(s).upper() for s in aff]
            if clean_sym not in aff_upper and ev.get("currency", "") not in clean_sym:
                if not (ev.get("currency") == "USD" and ("XAU" in clean_sym or "USD" in clean_sym)):
                    continue

            impact = ev.get("impact", "LOW").upper()
            pre_limit = PRE_EVENT_LOCKOUT_MINUTES.get(impact, 0)
            post_limit = POST_EVENT_COOLDOWN_MINUTES.get(impact, 0)

            try:
                ev_time = datetime.datetime.fromisoformat(ev["timestamp"])
                if ev_time.tzinfo is None:
                    ev_time = ev_time.replace(tzinfo=datetime.timezone.utc)
                else:
                    ev_time = ev_time.astimezone(datetime.timezone.utc)
            except Exception:
                continue

            time_diff_sec = (ev_time - now).total_seconds()
            diff_min = time_diff_sec / 60.0

            # Next upcoming event tracker (only Medium, High, Extreme)
            if diff_min >= 0:
                if impact in ["HIGH", "EXTREME", "MEDIUM"]:
                    if diff_min < min_to_next:
                        min_to_next = int(diff_min)
                        next_event_name = f"{ev.get('currency')} {ev.get('event_name')}"

                # Check Pre-Event Lockout (Blackout Window)
                if diff_min <= pre_limit and pre_limit > 0:
                    is_locked_out = True
                    lockout_type = "PRE_EVENT_BLACKOUT"
                    active_event = ev
                    rem_sec = int(time_diff_sec + (post_limit * 60))
                    seconds_remaining = max(seconds_remaining, rem_sec)
                    lockout_reason = (
                        f"Upcoming {impact}-Impact event '{ev.get('event_name')}' in {int(diff_min)}m "
                        f"(Blackout window: {pre_limit}m before release)."
                    )
            else:
                # Past event (diff_min is negative)
                elapsed_min = abs(diff_min)
                if impact in ["HIGH", "EXTREME", "MEDIUM"]:
                    if elapsed_min < min_since_last:
                        min_since_last = int(elapsed_min)

                # Check Post-Event Cooldown
                if elapsed_min <= post_limit and post_limit > 0:
                    is_locked_out = True
                    lockout_type = "POST_EVENT_COOLDOWN"
                    active_event = ev
                    rem_sec = int((post_limit * 60) - (elapsed_min * 60))
                    seconds_remaining = max(seconds_remaining, rem_sec)
                    lockout_reason = (
                        f"Post-News Volatility Cooldown active after {impact}-Impact '{ev.get('event_name')}' "
                        f"({int(elapsed_min)}m elapsed, {int(post_limit - elapsed_min)}m cooldown remaining)."
                    )

                # Check Post-Event Spread Normalization Guard
                elif elapsed_min <= (post_limit + 30) and current_spread is not None:
                    if current_spread > max_acceptable_post_news_spread:
                        is_locked_out = True
                        lockout_type = "POST_EVENT_SPREAD_GUARD"
                        active_event = ev
                        seconds_remaining = max(seconds_remaining, 120)
                        lockout_reason = (
                            f"Post-News Spread Guard: Spread (${current_spread:.2f}) remains elevated above "
                            f"safe threshold (${max_acceptable_post_news_spread:.2f}) following '{ev.get('event_name')}'."
                        )

        calendar_available = bool(events)
        if not calendar_available:
            is_locked_out = True
            lockout_type = "CALENDAR_UNAVAILABLE"
            lockout_reason = "Economic calendar data is unavailable; trading is blocked."

        # Log risk event on new lockout transition
        if is_locked_out and self._last_logged_lockout != lockout_reason:
            self._last_logged_lockout = lockout_reason
            db.log_risk_event(
                event_type="NEWS_LOCKOUT",
                account_id="LOCAL_ENGINE",
                severity="HIGH" if lockout_type == "PRE_EVENT_BLACKOUT" else "WARNING",
                details=lockout_reason or "Economic event protection lockout"
            )
        elif not is_locked_out:
            self._last_logged_lockout = None

        spread_status = "NORMAL"
        if current_spread is not None:
            if current_spread > max_acceptable_post_news_spread:
                spread_status = "ELEVATED"

        return {
            "symbol": clean_sym,
            "is_locked_out": is_locked_out,
            "lockout_reason": lockout_reason,
            "lockout_type": lockout_type,
            "active_event": active_event,
            "minutes_to_next_high_impact_news": min_to_next if min_to_next != 9999 else 999,
            "minutes_since_last_event": min_since_last if min_since_last != 9999 else 999,
            "next_event_name": next_event_name,
            "seconds_remaining": seconds_remaining,
            "current_spread": current_spread,
            "baseline_spread": baseline_spread,
            "max_acceptable_spread": max_acceptable_post_news_spread,
            "spread_status": spread_status,
            "timestamp_utc": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "calendar_available": calendar_available
        }

    def get_macro_status(self, symbol: str = "XAUUSD", current_spread: Optional[float] = None) -> Dict[str, Any]:
        """
        Returns macro status dictionary used by NoTradeGuardian, Consensus Engine, and API endpoints.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        lockout_info = self.check_lockout_status(symbol=symbol, current_spread=current_spread, now=now)

        # Get sentiment summary from DB
        sentiment_info = db.get_market_sentiment_summary(symbol=symbol)

        return {
            "minutes_to_next_high_impact_news": lockout_info["minutes_to_next_high_impact_news"],
            "minutes_since_last_event": lockout_info["minutes_since_last_event"],
            "next_event_name": lockout_info["next_event_name"],
            "is_locked_out": lockout_info["is_locked_out"],
            "lockout_reason": lockout_info["lockout_reason"],
            "lockout_type": lockout_info["lockout_type"],
            "seconds_remaining": lockout_info["seconds_remaining"],
            "usd_sentiment": sentiment_info.get("usd_bias", "NEUTRAL"),
            "gold_macro_bias": sentiment_info.get("gold_bias", "NEUTRAL"),
            "sentiment_score": sentiment_info.get("sentiment_score", 0.0),
            "calendar_source": "LIVE_ECONOMIC_CALENDAR_ENGINE" if lockout_info["calendar_available"] else "UNAVAILABLE",
            "calendar_available": lockout_info["calendar_available"],
            "last_checked_utc": now.strftime("%Y-%m-%d %H:%M:%S UTC")
        }

    def get_current_news_feed_bias(self, symbol: str = "XAUUSD") -> Dict[str, Any]:
        """Returns macroeconomic and news sentiment status dictionary."""
        return self.get_macro_status(symbol=symbol)


economic_calendar = EconomicCalendarService()
economic_calendar_service = economic_calendar

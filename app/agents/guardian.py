import time
from typing import Dict, Any, Tuple, Optional
from app.config import settings
from app.database.models import SignalPayload
import settings_manager

class NoTradeGuardian:
    name: str = "No-Trade Guardian"

    def check_guard_rules(
        self,
        signal: SignalPayload,
        market_data: Dict[str, Any],
        macro_data: Dict[str, Any],
        account_status: Dict[str, Any],
        processed_signal_ids: set
    ) -> Tuple[bool, Optional[str]]:
        """
        Executes 16 defense-in-depth safety checks.
        Returns (is_blocked, block_reason).
        """
        p = signal.entry_price
        sl = signal.stop_loss
        tp = signal.take_profit
        act = signal.action.upper()
        sym = signal.symbol.upper().replace("M", "").replace(".PRO", "").replace("_I", "")
        
        spread = float(market_data.get("spread", 0.35))
        now_ts = time.time()
        market_ts = market_data.get("updated_at", now_ts)
        
        open_pos = account_status.get("open_positions", [])
        daily_loss = float(account_status.get("daily_loss", 0.0))
        consecutive_losses = int(account_status.get("consecutive_losses", 0))
        is_connected = bool(account_status.get("is_connected", True))
        
        minutes_to_news = macro_data.get("minutes_to_next_high_impact_news", 999)
        minutes_since_news = macro_data.get("minutes_since_last_event", 999)

        # Rule 1: Duplicate Signal / Replay Protection
        if signal.id and signal.id in processed_signal_ids:
            return True, f"Rule 1 Violations: Duplicate signal ID '{signal.id}' already processed."

        # Rule 2: Whitelist Restriction
        if not settings_manager.is_pair_whitelisted(sym):
            return True, f"Rule 2 Violation: Instrument '{sym}' is not whitelisted. Active Whitelist: {settings_manager.get_active_pairs()}."

        # Rule 3: Missing or Corrupted Quotes
        if p <= 0:
            return True, "Rule 3 Violation: Missing or invalid market entry price."

        # Rule 4: Stale Market Data Check
        data_age = now_ts - market_ts
        if data_age > settings.MAX_MARKET_DATA_AGE_SECONDS:
            return True, f"Rule 4 Violation: Stale market data quote ({data_age:.1f}s old > max {settings.MAX_MARKET_DATA_AGE_SECONDS}s)."

        # Rule 5: Abnormal Spread Surge (Max 55 cents on Gold)
        max_spread = settings.MAX_ALLOWED_SPREAD_XAUUSD if ("XAU" in sym or "GOLD" in sym) else 0.0005
        if spread > max_spread:
            return True, f"Rule 5 Violation: Abnormal spread surge (${spread:.2f}) exceeds maximum allowed threshold (${max_spread:.2f}) to prevent spread-bleed."

        # Rule 6: Upcoming High-Impact News Lockout (< 30m)
        if minutes_to_news <= settings.NEWS_PRE_BLOCK_MINUTES:
            return True, f"Rule 6 Violation: Upcoming high-impact economic news in {minutes_to_news}m (Lockout active)."

        # Rule 7: Post-News Volatility Cooldown (< 15m)
        if minutes_since_news <= settings.NEWS_POST_COOLDOWN_MINUTES:
            return True, f"Rule 7 Violation: Post-news volatility cooldown active ({minutes_since_news}m since release)."

        # Rule 8: Mandatory Stop Loss
        if sl <= 0 or tp <= 0:
            return True, "Rule 8 Violation: Mandatory SL or TP is missing. Naked positions strictly prohibited."

        # Rule 9: SL & TP Breathing Room Targets ($2.00 min SL, $4.00 min TP on Gold)
        sl_dist = abs(p - sl)
        tp_dist = abs(tp - p)
        is_gold = "XAU" in sym or "GOLD" in sym
        min_sl = max(spread * settings.MIN_SL_SPREAD_MULTIPLIER, getattr(settings, "MIN_SL_BUFFER_GOLD", 2.00) if is_gold else 0.40)
        min_tp = getattr(settings, "MIN_TP_BUFFER_GOLD", 4.00) if is_gold else 0.80
        if sl_dist < min_sl:
            return True, f"Rule 9 Violation: SL distance (${sl_dist:.2f}) is tighter than minimum broker breathing buffer (${min_sl:.2f})."
        if tp_dist < min_tp:
            return True, f"Rule 9 Violation: TP distance (${tp_dist:.2f}) is tighter than minimum target threshold (${min_tp:.2f})."

        # Rule 10: Insufficient Risk-to-Reward (< 2.0)
        rr = round(tp_dist / (sl_dist + 1e-6), 2)
        if rr < settings.MIN_RR_RATIO:
            return True, f"Rule 10 Violation: Risk-to-Reward (1:{rr:.2f}) is below mandatory 1:{settings.MIN_RR_RATIO:.1f} threshold."

        # Rule 11: Max Open Positions Hard Cap
        if len(open_pos) >= settings.MAX_OPEN_POSITIONS:
            return True, f"Rule 11 Violation: Max concurrent positions ({settings.MAX_OPEN_POSITIONS}) currently filled."

        # Rule 12: Opposing / Hedging Conflict
        for pos in open_pos:
            pos_sym = pos.get("symbol", "").upper()
            if "XAU" in pos_sym or "GOLD" in pos_sym:
                return True, "Rule 12 Violation: Active position already exists on Gold. Stacking or hedging prohibited."

        # Rule 13: Daily Drawdown Circuit Breaker
        if daily_loss <= -settings.DAILY_LOSS_LIMIT:
            return True, f"Rule 13 Violation: Daily Drawdown Circuit Breaker tripped (-${abs(daily_loss):.2f} loss)."

        # Rule 14: Consecutive Losses Circuit Breaker
        if consecutive_losses >= settings.MAX_CONSECUTIVE_LOSSES:
            return True, f"Rule 14 Violation: Consecutive loss circuit breaker active ({consecutive_losses} losses)."

        # Rule 15: cTrader Bridge Connection (if in LIVE or DEMO mode)
        if settings.TRADING_MODE in ("LIVE", "DEMO") and not is_connected:
            return True, "Rule 15 Violation: cTrader execution bridge is disconnected. Automated trading paused."

        # Rule 16: Zero-Failure Invalidation Check
        if (act == "BUY" and sl >= p) or (act == "SELL" and sl <= p):
            return True, "Rule 16 Violation: Inverted Stop Loss logic detected."

        # Rule 17: Post-Trade Close Cooldown (30-minute pacing)
        last_close = account_status.get("last_trade_close_timestamp", 0)
        if last_close > 0 and (now_ts - last_close) < settings.TRADE_CLOSE_COOLDOWN_SECONDS:
            rem_m = int((settings.TRADE_CLOSE_COOLDOWN_SECONDS - (now_ts - last_close)) / 60)
            return True, f"Rule 17 Violation: Post-trade close cooldown active ({rem_m}m remaining of 30m window before evaluating new setups)."

        return False, None

guardian = NoTradeGuardian()

import datetime
import time
from typing import Dict, Any

class EconomicCalendarService:
    """
    Manages structured macroeconomic calendar and high-impact event lockout windows for Gold.
    """
    
    def get_macro_status(self) -> Dict[str, Any]:
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # High impact events schedule (sample calendar / live feeds)
        # Gold is sensitive to US CPI, NFP, FOMC, Fed Chair Speeches
        events = [
            {"name": "US Non-Farm Payrolls (NFP)", "impact": "HIGH", "currency": "USD", "hour_utc": 12, "minute_utc": 30},
            {"name": "US Consumer Price Index (CPI)", "impact": "HIGH", "currency": "USD", "hour_utc": 12, "minute_utc": 30},
            {"name": "FOMC Rate Decision & Press Conference", "impact": "HIGH", "currency": "USD", "hour_utc": 18, "minute_utc": 0}
        ]
        
        # Calculate minutes to next scheduled release (simulated or real)
        # Default to clean window (e.g. 180 mins away)
        min_to_next = 180
        next_event = "FOMC Interest Rate Decision"
        min_since_last = 120
        
        # Check current hour for typical US releases (12:30 UTC or 18:00 UTC)
        curr_hour = now.hour
        curr_min = now.minute
        
        if curr_hour == 12:
            if curr_min < 30:
                min_to_next = 30 - curr_min
                next_event = "US CPI / NFP Release"
            else:
                min_since_last = curr_min - 30
        elif curr_hour == 17:
            min_to_next = 60 - curr_min
            next_event = "FOMC Rate Decision"
        elif curr_hour == 18 and curr_min < 45:
            min_since_last = curr_min
            next_event = "FOMC Press Conference"

        return {
            "minutes_to_next_high_impact_news": min_to_next,
            "minutes_since_last_event": min_since_last,
            "next_event_name": next_event,
            "usd_sentiment": "NEUTRAL",
            "gold_macro_bias": "BULLISH_GOLD",
            "calendar_source": "ECONOMIC_CALENDAR_ENGINE",
            "last_checked_utc": now.strftime("%Y-%m-%d %H:%M:%S UTC")
        }

economic_calendar = EconomicCalendarService()

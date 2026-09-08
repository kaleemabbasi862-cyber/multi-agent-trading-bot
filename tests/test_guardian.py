from app.database.models import SignalPayload
from app.agents.guardian import guardian

def test_guardian_blocks_high_spread():
    sig = SignalPayload(
        symbol="XAUUSD",
        action="BUY",
        entry_price=2750.0,
        stop_loss=2744.0,
        take_profit=2762.0
    )
    import time
    market = {"spread": 2.50, "updated_at": time.time()} # excessive spread
    macro = {"minutes_to_next_high_impact_news": 120}
    acc = {"open_positions": [], "daily_loss": 0.0, "is_connected": True}
    
    blocked, reason = guardian.check_guard_rules(sig, market, macro, acc, set())
    assert blocked is True
    assert "Abnormal spread surge" in reason

def test_guardian_blocks_upcoming_news():
    sig = SignalPayload(
        symbol="XAUUSD",
        action="BUY",
        entry_price=2750.0,
        stop_loss=2744.0,
        take_profit=2762.0
    )
    import time
    market = {"spread": 0.20, "updated_at": time.time()}
    macro = {"minutes_to_next_high_impact_news": 10} # 10m to CPI
    acc = {"open_positions": [], "daily_loss": 0.0, "is_connected": True}
    
    blocked, reason = guardian.check_guard_rules(sig, market, macro, acc, set())
    assert blocked is True
    assert "Upcoming high-impact economic news" in reason

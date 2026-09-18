from datetime import datetime, timezone
from app.services.entry_safety_policy import (
    consecutive_loss_lockout,
    directional_location_block_reason,
)

def test_buy_is_blocked_in_extreme_premium():
    reason = directional_location_block_reason(
        "BUY", {"dealing_range": {"zone": "EXTREME_PREMIUM", "location_pct": 95.0}}
    )
    assert reason and reason.startswith("NO_TRADE_LOCATION_CHASE")

def test_sell_is_blocked_in_deep_discount():
    reason = directional_location_block_reason(
        "SELL", {"dealing_range": {"zone": "DEEP_DISCOUNT", "location_pct": 12.0}}
    )
    assert reason and reason.startswith("NO_TRADE_LOCATION_CHASE")

def test_directionally_favorable_locations_are_allowed():
    assert directional_location_block_reason(
        "BUY", {"dealing_range": {"zone": "DISCOUNT", "location_pct": 35.0}}
    ) is None
    assert directional_location_block_reason(
        "SELL", {"dealing_range": {"zone": "PREMIUM", "location_pct": 65.0}}
    ) is None

def test_two_recent_losses_trigger_one_hour_lockout():
    now = datetime.now(timezone.utc).timestamp()
    closed = datetime.now(timezone.utc).isoformat()
    rows = [
        {"status": "CLOSED", "profit_loss": -2.0, "closed_at": closed},
        {"status": "CLOSED", "profit_loss": -1.0, "closed_at": closed},
    ]
    locked, remaining = consecutive_loss_lockout(rows, now, 2, 3600)
    assert locked is True
    assert 3598 <= remaining <= 3600

def test_non_loss_breaks_loss_sequence():
    now = datetime.now(timezone.utc).timestamp()
    closed = datetime.now(timezone.utc).isoformat()
    rows = [
        {"status": "CLOSED", "profit_loss": -2.0, "closed_at": closed},
        {"status": "CLOSED", "profit_loss": 0.5, "closed_at": closed},
        {"status": "CLOSED", "profit_loss": -1.0, "closed_at": closed},
    ]
    assert consecutive_loss_lockout(rows, now, 2, 3600) == (False, 0)

def test_expired_loss_lockout_does_not_block():
    now = datetime.now(timezone.utc).timestamp()
    old = datetime.fromtimestamp(now - 3700, tz=timezone.utc).isoformat()
    rows = [
        {"status": "CLOSED", "profit_loss": -2.0, "closed_at": old},
        {"status": "CLOSED", "profit_loss": -1.0, "closed_at": old},
    ]
    assert consecutive_loss_lockout(rows, now, 2, 3600) == (False, 0)

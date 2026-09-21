from app.database.db import db
from app.services.adx_near_miss_tracker import adx_near_miss_tracker


def _scan(adx=19.5, quality=80.0, passed=True):
    return {
        "decision_reason": f"NO_TRADE_REGIME_ADX: ADX {adx} is below required minimum 20.0.",
        "setup": {
            "setup_type": "OB_REACTION",
            "direction": "SELL",
            "is_actionable": True,
            "regime": "INTRADAY_BEAR_TREND",
        },
        "quality_score": {"score": quality, "threshold": 75.0, "passed": passed},
        "indicators": {
            "adx": {"adx": adx, "plus_di": 15.0, "minus_di": 24.0}
        },
        "smc": {
            "structure": "BEARISH_TREND",
            "dealing_range": {"zone": "DISCOUNT"},
        },
    }


def _clear():
    with db.get_connection() as conn:
        conn.execute("DELETE FROM adx_near_miss_opportunities")
        conn.commit()


def test_records_eligible_near_miss_once_per_fifteen_minute_bucket():
    _clear()
    assert adx_near_miss_tracker.observe_scan(
        _scan(), entry_price=4358.0, symbol="XAUUSD", now_ts=1_800_000_000
    )
    assert not adx_near_miss_tracker.observe_scan(
        _scan(), entry_price=4357.0, symbol="XAUUSD", now_ts=1_800_000_010
    )
    rows = adx_near_miss_tracker.recent()
    assert len(rows) == 1
    assert rows[0]["direction"] == "SELL"
    assert rows[0]["status"] == "OPEN"
    assert rows[0]["result"] == "PENDING"


def test_does_not_record_outside_adx_band_or_failed_quality():
    _clear()
    assert not adx_near_miss_tracker.observe_scan(
        _scan(adx=17.9), entry_price=4358.0, symbol="XAUUSD", now_ts=1_800_000_000
    )
    assert not adx_near_miss_tracker.observe_scan(
        _scan(adx=19.5, passed=False), entry_price=4358.0,
        symbol="XAUUSD", now_ts=1_800_000_000
    )
    assert adx_near_miss_tracker.recent() == []


def test_resolves_two_r_target_from_broker_price_path():
    _clear()
    now = 1_800_000_000
    adx_near_miss_tracker.observe_scan(
        _scan(), entry_price=4358.0, symbol="XAUUSD", now_ts=now
    )
    adx_near_miss_tracker.update_open("XAUUSD", 4352.0, now_ts=now + 60)
    row = adx_near_miss_tracker.recent()[0]
    assert row["status"] == "OPEN"
    assert row["hit_1r_at"]

    adx_near_miss_tracker.update_open("XAUUSD", 4346.0, now_ts=now + 120)
    row = adx_near_miss_tracker.recent()[0]
    assert row["status"] == "RESOLVED"
    assert row["result"] == "TARGET_2R"
    assert row["max_favorable_r"] == 2.0


def test_resolves_stop_and_preserves_adverse_excursion():
    _clear()
    now = 1_800_000_000
    adx_near_miss_tracker.observe_scan(
        _scan(), entry_price=4358.0, symbol="XAUUSD", now_ts=now
    )
    adx_near_miss_tracker.update_open("XAUUSD", 4364.0, now_ts=now + 60)
    row = adx_near_miss_tracker.recent()[0]
    assert row["status"] == "RESOLVED"
    assert row["result"] == "STOP_1R"
    assert row["max_adverse_r"] == -1.0

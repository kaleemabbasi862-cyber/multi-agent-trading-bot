import unittest
import datetime
from app.services.risk_engine import risk_engine
from app.database.db import db
from fastapi.testclient import TestClient
from main_native import app

client = TestClient(app)

def test_dynamic_position_sizing_standard_account():
    """Validates position size calculation on standard account ($10,000 equity, 1% risk = $100)."""
    # Gold entry 2350, SL 2345 (SL dist = $5.00). 1 Lot = 100 oz.
    # $100 risk / ($5 * 100) = 0.20 Lots
    res = risk_engine.calculate_position_size(
        symbol="XAUUSD",
        account_equity=10000.0,
        entry_price=2350.0,
        stop_loss=2345.0,
        risk_percentage=1.0,
        max_lot_cap=1.00
    )
    assert res["status"] == "CALCULATED"
    assert res["calculated_volume"] == 0.20, f"Expected 0.20 lots, got {res['calculated_volume']}"
    assert res["risk_amount_dollars"] == 100.0

def test_dynamic_position_sizing_micro_account():
    """Validates position sizing clamping on micro account ($38 equity, minimum 0.01 lot)."""
    res = risk_engine.calculate_position_size(
        symbol="XAUUSD",
        account_equity=38.0,
        entry_price=2350.0,
        stop_loss=2346.0,
        risk_percentage=1.0,
        max_lot_cap=0.01
    )
    assert res["calculated_volume"] == 0.01, f"Expected 0.01 lots floor, got {res['calculated_volume']}"

def test_daily_drawdown_circuit_breaker():
    """Validates circuit breaker trip when daily loss hits threshold (-$5.00)."""
    acc_status_safe = {"balance": 1000.0, "equity": 1000.0, "daily_loss": -2.00, "consecutive_losses": 0}
    tripped, reason, severity = risk_engine.check_circuit_breakers(acc_status_safe)
    assert not tripped, "Should not trip on -$2.00 daily loss"

    acc_status_tripped = {"balance": 1000.0, "equity": 990.0, "daily_loss": -5.50, "consecutive_losses": 0, "account_id": "TEST_ACC"}
    tripped, reason, severity = risk_engine.check_circuit_breakers(acc_status_tripped)
    assert tripped, "Must trip when daily loss exceeds -$5.00"
    assert severity == "HIGH"
    assert "Daily Loss Circuit Breaker Tripped" in reason

    # Check risk_events table
    events = db.get_risk_events(limit=5)
    assert any(e["event_type"] == "CIRCUIT_BREAKER" for e in events), "Circuit breaker event must be saved in DB"

def test_consecutive_losses_cooldown_and_reset():
    """Validates 3 consecutive losses triggering 60-minute cooldown and manual reset."""
    acc_status_losses = {"balance": 1000.0, "equity": 995.0, "daily_loss": -3.00, "consecutive_losses": 3}
    tripped, reason, severity = risk_engine.check_circuit_breakers(acc_status_losses)
    assert tripped, "Must trip on 3 consecutive losses"
    assert "Consecutive Loss Circuit Breaker" in reason

    # Reset
    reset_res = risk_engine.reset_circuit_breaker()
    assert reset_res["status"] == "SUCCESS"

def test_risk_api_endpoints():
    """Validates FastAPI risk endpoints."""
    # GET /api/risk/telemetry
    res_tel = client.get("/api/risk/telemetry")
    assert res_tel.status_code == 200
    assert "daily_loss_limit" in res_tel.json()["data"]

    # POST /api/risk/calculate-size
    res_calc = client.post("/api/risk/calculate-size", json={
        "symbol": "XAUUSD",
        "account_equity": 5000.0,
        "entry_price": 2350.0,
        "stop_loss": 2345.0,
        "risk_percentage": 1.0,
        "max_lot_cap": 0.50
    })
    assert res_calc.status_code == 200
    assert res_calc.json()["data"]["calculated_volume"] == 0.10

    # POST /api/risk/circuit-breaker/reset
    res_reset = client.post("/api/risk/circuit-breaker/reset")
    assert res_reset.status_code == 200
    assert res_reset.json()["status"] == "SUCCESS"


class TestPhase6Risk(unittest.TestCase):
    def test_01_sizing_standard(self):
        test_dynamic_position_sizing_standard_account()

    def test_02_sizing_micro(self):
        test_dynamic_position_sizing_micro_account()

    def test_03_circuit_breaker(self):
        test_daily_drawdown_circuit_breaker()

    def test_04_consecutive_losses(self):
        test_consecutive_losses_cooldown_and_reset()

    def test_05_api(self):
        test_risk_api_endpoints()


if __name__ == "__main__":
    unittest.main()

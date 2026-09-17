import os
import sys

sys.path.insert(0, r"d:\Users\AL RAZZAQ\Desktop\Trade Talk")

from app.services.live_safety_gate import live_safety_gate
from app.services.position_sentinel import position_sentinel
from app.services.ctrader_execution_service import ctrader_execution_service
from unittest.mock import patch
import ctrader_cloud_gateway
from tests.broker_fixtures import install_state

def setup_function():
    ctrader_cloud_gateway.switch_active_account("5908018")
    install_state(ctrader_cloud_gateway, bid=2749.9, ask=2750.0)

BROKER_QUOTE = {"bid": 2749.9, "ask": 2750.0, "spread": 0.1}

@patch("app.services.live_safety_gate.ctrader_cloud_gateway.get_live_price", return_value=BROKER_QUOTE)
def test_strict_sltp_geometry_buy_inverted(_quote):
    """Test that BUY with inverted SL (SL >= Entry or TP <= Entry) is strictly VETOED."""
    setup_function()
    is_safe, reason, telemetry = live_safety_gate.evaluate_order_safety(
        symbol="XAUUSD",
        action="BUY",
        volume=0.01,
        entry_price=2750.0,
        sl_price=2755.0,
        tp_price=2765.0,
        ignore_news_lockout=True
    )
    assert is_safe is False
    assert "VETO_INVALID_SLTP_GEOMETRY" in reason

@patch("app.services.live_safety_gate.ctrader_cloud_gateway.get_live_price", return_value=BROKER_QUOTE)
def test_strict_sltp_geometry_sell_inverted(_quote):
    """Test that SELL with inverted SL (SL <= Entry or TP >= Entry) is strictly VETOED."""
    setup_function()
    is_safe, reason, telemetry = live_safety_gate.evaluate_order_safety(
        symbol="XAUUSD",
        action="SELL",
        volume=0.01,
        entry_price=2750.0,
        sl_price=2745.0,
        tp_price=2735.0,
        ignore_news_lockout=True
    )
    assert is_safe is False
    assert "VETO_INVALID_SLTP_GEOMETRY" in reason

@patch("app.services.live_safety_gate.ctrader_cloud_gateway.get_live_price", return_value=BROKER_QUOTE)
def test_strict_sltp_minimum_buffer_too_tight(_quote):
    """Test that SL too close to entry (< $3.50 on Gold) is strictly VETOED."""
    setup_function()
    is_safe, reason, telemetry = live_safety_gate.evaluate_order_safety(
        symbol="XAUUSD",
        action="BUY",
        volume=0.01,
        entry_price=2750.0,
        sl_price=2749.0,
        tp_price=2762.0,
        ignore_news_lockout=True
    )
    assert is_safe is False
    assert "VETO_STOP_LOSS_TOO_TIGHT" in reason

@patch("app.services.live_safety_gate.ctrader_cloud_gateway.get_live_price", return_value=BROKER_QUOTE)
def test_strict_sltp_valid_order_passes(_quote):
    """Test that valid BUY (SL $6.00 below entry, TP $12.00 above entry) PASSES."""
    setup_function()
    is_safe, reason, telemetry = live_safety_gate.evaluate_order_safety(
        symbol="XAUUSD",
        action="BUY",
        volume=0.01,
        entry_price=2750.0,
        sl_price=2744.0,
        tp_price=2762.0,
        current_spread_pips=1.5,
        ignore_news_lockout=True
    )
    assert is_safe is True
    assert "SAFETY_GATES_PASSED" in reason

def test_position_sentinel_no_premature_reversal_close():
    """Test that PositionSentinel NEVER force-closes a losing position due to indicator fluctuations."""
    fake_pos = {
        "id": "999888",
        "symbol": "XAUUSD",
        "type": "BUY",
        "entry_price": 2750.0,
        "sl_price": 2744.0,
        "tp_price": 2762.0,
        "current_price": 2748.20,
        "net_profit": -1.80,
        "unrealized_pnl": -1.80
    }
    ctrader_execution_service._positions_cache["999888"] = fake_pos
    actions = position_sentinel.evaluate_open_positions()
    reversal_closes = [a for a in actions if a.get("action") == "AUTONOMOUS_REVERSAL_EXIT"]
    assert len(reversal_closes) == 0, "PositionSentinel must NOT close losing position on indicator change!"
    ctrader_execution_service._positions_cache.pop("999888", None)

def test_state_reconciliation():
    """Test authoritative state reconciliation."""
    rec = ctrader_execution_service.reconcile_positions()
    assert "is_synced" in rec
    assert "status" in rec

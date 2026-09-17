import unittest
import time
from fastapi.testclient import TestClient
from main_native import app
from app.services.credential_store import credential_store
from app.services.risk_engine import risk_engine
from app.services.live_safety_gate import live_safety_gate
from app.services.autonomous_trader import autonomous_trader
import ctrader_cloud_gateway
from unittest.mock import patch, Mock
from tests.broker_fixtures import install_state

BROKER_QUOTE = {"bid": 2749.9, "ask": 2750.0, "spread": 0.1, "quote_at": "2026-09-16T12:00:00+00:00"}

class TestPhase10LiveSafetyAndAutonomousIntegration(unittest.TestCase):
    """
    Test suite for Phase 10: Live Safety Gatekeeper, Emergency Kill Switch,
    and Autonomous Multi-Agent Trading System.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        ctrader_cloud_gateway.switch_active_account("5908018")

    def setUp(self):
        credential_store.set_kill_switch(False)
        risk_engine.reset_circuit_breaker()
        ctrader_cloud_gateway.reset_cooldown()
        ctrader_cloud_gateway.GATEWAY_STATE["open_positions"] = []
        install_state(ctrader_cloud_gateway, bid=2749.9, ask=2750.0)
        from app.services.ctrader_execution_service import ctrader_execution_service
        ctrader_execution_service._positions_cache.clear()

    @patch("ctrader_cloud_gateway.get_live_price", return_value=BROKER_QUOTE)
    def test_01_safety_gate_passes_valid_setup(self, _quote):
        """Test that a compliant setup passes all 6 institutional safety gates."""
        is_safe, reason, telemetry = live_safety_gate.evaluate_order_safety(
            symbol="XAUUSD",
            action="BUY",
            volume=0.01,
            entry_price=2750.00,
            sl_price=2744.00,
            tp_price=2762.00,
            current_spread_pips=0.35,
            ignore_news_lockout=True
        )
        self.assertTrue(is_safe)
        self.assertIn("SAFETY_GATES_PASSED", reason)
        self.assertEqual(telemetry["status"], "APPROVED")

    def test_02_safety_gate_kill_switch_veto(self):
        """Test that emergency kill switch immediately locks out order execution."""
        credential_store.set_kill_switch(True)
        is_safe, reason, telemetry = live_safety_gate.evaluate_order_safety(
            symbol="XAUUSD",
            action="BUY",
            volume=0.01,
            entry_price=2750.00,
            sl_price=2744.00,
            tp_price=2762.00,
            ignore_news_lockout=True
        )
        self.assertFalse(is_safe)
        self.assertIn("KILL_SWITCH", reason)
        self.assertEqual(telemetry["status"], "LOCKED")

    @patch("ctrader_cloud_gateway.get_live_price", return_value=BROKER_QUOTE)
    def test_03_safety_gate_excessive_spread_veto(self, _quote):
        """Test that high spread beyond safety threshold is blocked."""
        is_safe, reason, telemetry = live_safety_gate.evaluate_order_safety(
            symbol="XAUUSD",
            action="BUY",
            volume=0.01,
            entry_price=2750.00,
            sl_price=2744.00,
            tp_price=2762.00,
            current_spread_pips=5.5, # Excessive spread > 3.5 pips
            ignore_news_lockout=True
        )
        self.assertFalse(is_safe)
        self.assertIn("EXCESSIVE_SPREAD", reason)

    @patch("ctrader_cloud_gateway.get_live_price", return_value=BROKER_QUOTE)
    def test_04_safety_gate_insufficient_rr_veto(self, _quote):
        """Test that setups with less than 1.5:1 R:R are vetoed."""
        is_safe, reason, telemetry = live_safety_gate.evaluate_order_safety(
            symbol="XAUUSD",
            action="BUY",
            volume=0.01,
            entry_price=2750.00,
            sl_price=2740.00, # Risk = 10
            tp_price=2755.00, # Reward = 5 (R:R = 0.5:1)
            ignore_news_lockout=True
        )
        self.assertFalse(is_safe)
        self.assertIn("INSUFFICIENT_RR", reason)

    @patch("ctrader_cloud_gateway.get_live_price", return_value=BROKER_QUOTE)
    @patch("app.services.autonomous_trader.live_safety_gate.evaluate_order_safety", return_value=(True, "OK", {}))
    @patch("app.services.autonomous_trader.consensus_engine.process_signal")
    @patch("app.services.autonomous_trader.ctrader_execution_service.execute_market_order")
    def test_05_autonomous_trader_lifecycle_and_setup_pipeline(self, mock_execute, mock_consensus, _safety, _quote):
        """Test autonomous lifecycle independently from consensus-engine state."""
        mock_consensus.return_value = Mock()
        mock_consensus.return_value.dict.return_value = {"decision_status": "APPROVED", "decision_score": 90.0, "signal_id": "SIG_PHASE10_LIFECYCLE"}
        mock_execute.return_value = {"status": "SUCCESS", "ticket": 91005, "position_id": 91005, "entry_price": 2750.0, "symbol": "XAUUSD"}
        # 1. Test Toggle
        status_init = autonomous_trader.get_status()["is_running"]
        toggled = autonomous_trader.toggle()
        self.assertEqual(toggled, not status_init)
        autonomous_trader.start()
        self.assertTrue(autonomous_trader.is_running)

        # 2. Process Setup through Autonomous Pipeline (mocking bridge fill)
        from app.services.market_data_integrity_monitor import market_data_integrity_monitor
        market_data_integrity_monitor.record_and_validate_tick("XAUUSD", 2749.80, 2750.20, time.time())

        ctrader_cloud_gateway.reset_cooldown()
        orig_dispatch = ctrader_cloud_gateway.dispatch_local_bridge_order
        ctrader_cloud_gateway.dispatch_local_bridge_order = lambda *args, **kwargs: {
            "status": "SUCCESS", "ticket": 91005, "position_id": 91005, "entry_price": 2750.00, "symbol": "XAUUSD"
        }
        try:
            res = autonomous_trader.process_market_setup(
                symbol="XAUUSD",
                action="BUY",
                entry_price=2750.00,
                stop_loss=2744.00,
                take_profit=2762.00,
                timeframe="15m"
            )
            self.assertEqual(res["status"], "SUCCESS")
            self.assertIn("consensus_result", res)
            mock_execute.assert_called_once()
        finally:
            ctrader_cloud_gateway.dispatch_local_bridge_order = orig_dispatch

    def test_06_autonomous_break_even_management_scan(self):
        """Test autonomous monitor scanning open trades and triggering break-even when hitting 1R profit."""
        # Setup position with entry 2750.0, SL 2745.0 (1R = 5.0).
        pos = {
            "id": "POS_91006",
            "ticket": "POS_91006",
            "symbol": "XAUUSD",
            "type": "BUY",
            "volume": 0.01,
            "lot_size": 0.01,
            "entry_price": 2750.00,
            "current_price": 2756.00, # Profit is +6.0 (> 1R)
            "sl_price": 2745.00,
            "tp_price": 2765.00,
            "net_profit": 6.00
        }
        ctrader_cloud_gateway.GATEWAY_STATE["open_positions"] = [pos]

        # Trigger management scan with broker-authoritative live quote at 2756.00
        with patch("ctrader_cloud_gateway.get_live_price", return_value={"bid": 2756.0, "ask": 2756.1, "price": 2756.05, "spread": 0.1, "quote_at": "2026-09-16T12:00:00+00:00"}):
            updates = autonomous_trader.check_and_manage_open_positions({"XAUUSD": 2756.00})
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["action"], "MOVED_TO_BREAK_EVEN")

    @patch("ctrader_cloud_gateway.get_live_price", return_value=BROKER_QUOTE)
    def test_07_phase10_rest_api_endpoints(self, _quote):
        """Test FastAPI REST endpoints for live safety check, autonomous toggle & status."""
        # 1. Safety Check API
        res_check = self.client.post("/api/execution/safety-check?symbol=XAUUSD&action=BUY&volume=0.01&entry_price=2750.0&sl_price=2744.0&tp_price=2762.0&ignore_news_lockout=true")
        self.assertEqual(res_check.status_code, 200)
        self.assertTrue(res_check.json()["is_approved"])

        # 2. Autonomous Toggle API
        res_toggle = self.client.post("/api/execution/autonomous/toggle")
        self.assertEqual(res_toggle.status_code, 200)
        self.assertIn("is_running", res_toggle.json())

        # 3. Autonomous Status API
        res_status = self.client.get("/api/execution/autonomous/status")
        self.assertEqual(res_status.status_code, 200)
        self.assertIn("trailing_enabled", res_status.json())
        self.assertIn("break_even_enabled", res_status.json())

if __name__ == "__main__":
    unittest.main()

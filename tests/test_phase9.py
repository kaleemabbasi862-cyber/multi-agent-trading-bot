import unittest
from fastapi.testclient import TestClient
from main_native import app
from app.services.ctrader_execution_service import ctrader_execution_service
import ctrader_cloud_gateway
from unittest.mock import patch, Mock
import os
from tests.broker_fixtures import install_state

BROKER_QUOTE = {"bid": 2749.9, "ask": 2750.0, "price": 2749.95, "spread": 0.1, "quote_at": "2026-09-16T12:00:00+00:00"}

class TestPhase9CTraderExecution(unittest.TestCase):
    """
    Test suite for Phase 9: cTrader Order Execution, SL/TP Modification,
    Move-to-Break-Even, and Partial Position Closes.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        ctrader_cloud_gateway.switch_active_account("5908018")

    def setUp(self):
        self._testing_prev = os.environ.get("TESTING")
        os.environ["TESTING"] = "0"
        # Reset open positions, cooldown state, and circuit breaker before each test
        ctrader_cloud_gateway.reset_cooldown()
        ctrader_cloud_gateway.GATEWAY_STATE["open_positions"] = []
        install_state(ctrader_cloud_gateway, bid=2749.9, ask=2750.0)
        ctrader_cloud_gateway.get_active_account()["open_positions"] = []
        ctrader_execution_service._positions_cache.clear()
        from app.services.risk_engine import risk_engine
        risk_engine.reset_circuit_breaker()

    def tearDown(self):
        if self._testing_prev is None: os.environ.pop("TESTING", None)
        else: os.environ["TESTING"] = self._testing_prev

    @patch("ctrader_cloud_gateway.get_live_price", return_value=BROKER_QUOTE)
    def test_01_market_order_execution(self, _quote):
        """Test submitting market order through cTrader Open API execution service."""
        orig_dispatch = ctrader_cloud_gateway.dispatch_local_bridge_order
        ctrader_cloud_gateway.dispatch_local_bridge_order = lambda *args, **kwargs: {
            "status": "SUCCESS", "position_id": 91001, "entry_price": 2750.00, "symbol": "XAUUSD"
        }
        try:
            res = ctrader_execution_service.execute_market_order(
                symbol="XAUUSD",
                action="BUY",
                volume=0.01,
                sl_price=2744.00,
                tp_price=2762.00,
                comment="Phase 9 Unit Test",
                ignore_news_lockout=True
            )
            self.assertEqual(res["status"], "SUCCESS")
            self.assertEqual(res["symbol"], "XAUUSD")
            self.assertEqual(res["action"], "BUY")
            self.assertEqual(res["lot_size"], 0.01)
            self.assertEqual(len(ctrader_execution_service.get_open_positions()), 1)
        finally:
            ctrader_cloud_gateway.dispatch_local_bridge_order = orig_dispatch

    @patch("ctrader_cloud_gateway.get_live_price", return_value=BROKER_QUOTE)
    @patch("app.services.ctrader_execution_service.requests.post")
    def test_02_modify_sltp_and_move_to_break_even(self, mock_post, _quote):
        """Test modifying stop-loss / take-profit and moving to break-even."""
        mock_post.return_value = Mock(status_code=200)
        mock_post.return_value.json.return_value = {"status": "SUCCESS"}
        # Seed an open position
        pos = {
            "id": "POS_91002",
            "ticket": "POS_91002",
            "symbol": "XAUUSD",
            "type": "BUY",
            "volume": 0.02,
            "lot_size": 0.02,
            "entry_price": 2750.00,
            "current_price": 2755.00,
            "sl_price": 2744.00,
            "tp_price": 2765.00,
            "net_profit": 10.00
        }
        ctrader_cloud_gateway.GATEWAY_STATE["open_positions"] = [pos]

        # 1. Test SL/TP Modification
        mod_res = ctrader_execution_service.modify_position_sltp(
            position_id="POS_91002",
            new_sl=2748.50,
            new_tp=2770.00
        )
        self.assertEqual(mod_res["status"], "SUCCESS")
        self.assertEqual(mod_res["sl_price"], 2748.50)
        self.assertEqual(mod_res["tp_price"], 2770.00)

        # 2. Test Move to Break-Even (2750.00 + 1.0 pip = 2750.01)
        be_res = ctrader_execution_service.move_to_break_even(
            position_id="POS_91002",
            buffer_pips=1.0
        )
        self.assertEqual(be_res["status"], "SUCCESS")
        self.assertGreaterEqual(be_res["sl_price"], 2750.00)

    def test_03_partial_close_position(self):
        """Test partial close (closing 0.01 out of 0.02 lots) with PnL calculation."""
        pos = {
            "id": "POS_91003",
            "ticket": "POS_91003",
            "symbol": "XAUUSD",
            "type": "BUY",
            "volume": 0.02,
            "lot_size": 0.02,
            "entry_price": 2750.00,
            "current_price": 2760.00,
            "sl_price": 2745.00,
            "tp_price": 2770.00,
            "net_profit": 20.00
        }
        ctrader_cloud_gateway.GATEWAY_STATE["open_positions"] = [pos]

        part_res = ctrader_execution_service.partial_close_position(
            position_id="POS_91003",
            close_volume=0.01
        )
        self.assertEqual(part_res["status"], "REJECTED_UNSUPPORTED_BROKER_OPERATION")
        self.assertEqual(ctrader_cloud_gateway.GATEWAY_STATE["open_positions"][0]["volume"], 0.02)

    @patch("ctrader_cloud_gateway.get_live_price", return_value=BROKER_QUOTE)
    @patch("app.services.ctrader_execution_service.requests.post")
    def test_04_execution_rest_api_endpoints(self, mock_post, _quote):
        """Test FastAPI REST endpoints for execution, SL/TP modify, break-even, and partial close."""
        mock_post.return_value = Mock(status_code=200)
        mock_post.return_value.json.return_value = {"status": "SUCCESS"}
        # 1. Market Order API
        ctrader_cloud_gateway.reset_cooldown()
        ctrader_cloud_gateway.GATEWAY_STATE["open_positions"] = []
        ctrader_execution_service._positions_cache.clear()
        orig_dispatch = ctrader_cloud_gateway.dispatch_local_bridge_order
        ctrader_cloud_gateway.dispatch_local_bridge_order = lambda *args, **kwargs: {
            "status": "SUCCESS", "position_id": 91004, "entry_price": 2750.00, "symbol": "XAUUSD"
        }
        try:
            res_order = self.client.post("/api/execution/order", json={
                "symbol": "XAUUSD",
                "action": "BUY",
                "volume": 0.01,
                "sl_price": 2744.00,
                "tp_price": 2762.00,
                "ignore_news_lockout": True
            })
            self.assertEqual(res_order.status_code, 200)
            data_order = res_order.json()
            self.assertEqual(data_order["status"], "SUCCESS")
        finally:
            ctrader_cloud_gateway.dispatch_local_bridge_order = orig_dispatch

        # 2. Get Positions API
        res_pos = self.client.get("/api/execution/positions")
        self.assertEqual(res_pos.status_code, 200)
        data_pos = res_pos.json()
        self.assertIn("open_positions", data_pos)
        self.assertIn("summary", data_pos)

        # 3. Modify SL/TP API
        open_pos_id = data_pos["open_positions"][0]["id"]
        res_mod = self.client.post("/api/execution/modify-sltp", json={
            "position_id": open_pos_id,
            "sl_price": 2747.00,
            "tp_price": 2765.00
        })
        self.assertEqual(res_mod.status_code, 200)
        self.assertEqual(res_mod.json()["status"], "SUCCESS")

        # 4. Break-Even API
        res_be = self.client.post("/api/execution/break-even", json={
            "position_id": open_pos_id,
            "buffer_pips": 1.5
        })
        self.assertEqual(res_be.status_code, 200)
        self.assertEqual(res_be.json()["status"], "SUCCESS")

        # 5. Close Position API
        res_close = self.client.post("/api/execution/close", json={
            "position_id": open_pos_id,
            "force": True
        })
        self.assertEqual(res_close.status_code, 200)
        self.assertEqual(res_close.json()["status"], "SUCCESS")

if __name__ == "__main__":
    unittest.main()

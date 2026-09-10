"""
Phase 6 source-integrity regression tests.

These tests pin the prospective 2.1.0-DEMO-CANDIDATE invariants found during
the independent repository audit. They intentionally test fail-closed behavior
without requiring a broker connection.
"""
import os
import unittest
from unittest.mock import patch

os.environ["TESTING"] = "1"

from app.config import settings, trading_config
from app.services.pretrade_intelligence_engine import pretrade_intelligence_engine
import ctrader_cloud_gateway as gateway


class TestPhase6SourceIntegrity(unittest.TestCase):
    def setUp(self):
        self.original_state = dict(gateway.GATEWAY_STATE)
        gateway.GATEWAY_STATE["open_positions"] = []
        gateway.LAST_EXECUTION_TIMESTAMP = 0
        gateway.LAST_TRADE_CLOSE_TIMESTAMP = 0

    def tearDown(self):
        gateway.GATEWAY_STATE.clear()
        gateway.GATEWAY_STATE.update(self.original_state)

    def test_candidate_constants_are_registered(self):
        self.assertEqual(trading_config.version, "2.1.0-DEMO-CANDIDATE")
        self.assertEqual(trading_config.get("REGIME_ADX_MINIMUM"), 20.0)
        self.assertTrue(trading_config.get("DISALLOW_CONSOLIDATION_ENTRIES"))

    def test_candidate_defaults_to_demo_environment(self):
        self.assertEqual(settings.TRADING_MODE, "DEMO")
        self.assertEqual(settings.CTRADER_ENVIRONMENT.lower(), "demo")

    def test_gateway_blocks_live_account_execution(self):
        gateway.GATEWAY_STATE["is_live"] = True
        gateway.GATEWAY_STATE["account_type"] = "LIVE"
        result = gateway.execute_market_order(
            symbol="XAUUSD", action="BUY", lot_size=0.01,
            sl_price=4990.0, tp_price=5020.0, signal_id="TEST_LIVE_BLOCK"
        )
        self.assertEqual(result["status"], "REJECTED_DEMO_ONLY_CANDIDATE")

    def test_gateway_rejects_missing_live_price(self):
        gateway.GATEWAY_STATE["is_live"] = False
        gateway.GATEWAY_STATE["account_type"] = "DEMO"
        gateway.GATEWAY_STATE["live_prices"] = {}
        result = gateway.execute_market_order(
            symbol="XAUUSD", action="BUY", lot_size=0.01,
            sl_price=4990.0, tp_price=5020.0, signal_id="TEST_NO_PRICE"
        )
        self.assertEqual(result["status"], "REJECTED_UNVERIFIED_MARKET_DATA")
        self.assertEqual(gateway.GATEWAY_STATE["open_positions"], [])

    @patch("ctrader_cloud_gateway.dispatch_local_bridge_order")
    def test_gateway_does_not_create_ghost_position_on_bridge_failure(self, dispatch):
        gateway.GATEWAY_STATE["is_live"] = False
        gateway.GATEWAY_STATE["account_type"] = "DEMO"
        gateway.GATEWAY_STATE["live_prices"] = {
            "XAUUSD": {"price": 5000.0, "spread": 0.10}
        }
        dispatch.return_value = {"status": "OFFLINE", "message": "bridge unavailable"}
        result = gateway.execute_market_order(
            symbol="XAUUSD", action="BUY", lot_size=0.01,
            sl_price=4994.0, tp_price=5012.0, signal_id="TEST_GHOST_BLOCK"
        )
        self.assertEqual(result["status"], "REJECTED_BROKER_EXECUTION_UNCONFIRMED")
        self.assertEqual(gateway.GATEWAY_STATE["open_positions"], [])


if __name__ == "__main__":
    unittest.main()

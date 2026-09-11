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
from tests.broker_fixtures import install_state


class TestPhase6SourceIntegrity(unittest.TestCase):
    def setUp(self):
        self.original_state = dict(gateway.GATEWAY_STATE)
        install_state(gateway)
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
        gateway.GATEWAY_STATE["broker_prices"] = {}
        result = gateway.execute_market_order(
            symbol="XAUUSD", action="BUY", lot_size=0.01,
            sl_price=4990.0, tp_price=5020.0, signal_id="TEST_NO_PRICE"
        )
        self.assertEqual(result["status"], "REJECTED_BROKER_TELEMETRY")
        self.assertEqual(result["error"], "BROKER_QUOTE_UNVERIFIED")
        self.assertEqual(gateway.GATEWAY_STATE["open_positions"], [])

    @patch("ctrader_cloud_gateway.dispatch_local_bridge_order")
    def test_gateway_rejects_invalid_geometry_without_rewriting_levels(self, dispatch):
        gateway.GATEWAY_STATE["is_live"] = False
        gateway.GATEWAY_STATE["account_type"] = "DEMO"
        gateway.GATEWAY_STATE["live_prices"] = {
            "XAUUSD": {"price": 5000.0, "spread": 0.10}
        }
        result = gateway.execute_market_order(
            symbol="XAUUSD", action="BUY", lot_size=0.01,
            sl_price=5001.0, tp_price=5012.0, signal_id="TEST_GEOMETRY"
        )
        self.assertEqual(result["status"], "REJECTED_INVALID_PROTECTION_GEOMETRY")
        dispatch.assert_not_called()
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

    def test_testing_mode_blocks_real_external_broker_dispatch(self):
        """Verify that when TESTING=1, unmocked dispatch_local_bridge_order fails closed without network call."""
        res = gateway.dispatch_local_bridge_order(
            symbol="XAUUSD",
            side="BUY",
            volume=0.01,
            sl_price=2744.0,
            tp_price=2762.0,
            comment="Unmocked Test Dispatch"
        )
        self.assertEqual(res.get("status"), "REJECTED_TEST_MODE_EXTERNAL_EXECUTION_BLOCKED")
        self.assertIn("strictly prohibited", res.get("error", ""))

    def test_database_isolation_in_test_environment(self):
        """Verify that test database path is isolated from production tradetalk_v2.db."""
        import app.config
        test_db = app.config.settings.DATABASE_PATH
        prod_db = str(app.config.BASE_DIR / "tradetalk_v2.db")
        self.assertTrue(os.environ.get("TESTING") == "1")
        if os.environ.get("DATABASE_PATH"):
            self.assertNotEqual(test_db, prod_db)
            self.assertTrue("tradetalk_test_" in test_db or "test" in test_db.lower())


if __name__ == "__main__":
    unittest.main()

"""Freshness, identity, quote provenance and no-dispatch regression tests."""
import asyncio
import copy
import os
import time
from unittest.mock import patch, Mock

os.environ["TESTING"] = "1"
import ctrader_cloud_gateway as gateway
from app.services import broker_telemetry
from tests.broker_fixtures import snapshot, install_state
from tests.test_broker_reconciliation import BrokerDatabaseFixture
from cloud_telemetry_relay import build_heartbeat_payload


class TestBrokerTelemetry(BrokerDatabaseFixture):
    def order(self):
        gateway.LAST_EXECUTION_TIMESTAMP = 0
        gateway.LAST_TRADE_CLOSE_TIMESTAMP = 0
        return gateway.execute_market_order("XAUUSD", "BUY", 0.01, 4310, 4335)

    def test_audit_snapshot_updates_account_and_executable_bid_ask(self):
        self.seed("ghost", "DEMO", ticket="287480624")
        result = gateway.update_heartbeat(build_heartbeat_payload(snapshot()))
        self.assertEqual(result["status"], "ACCEPTED")
        self.assertEqual(gateway.GATEWAY_STATE["balance"], 998.81)
        self.assertEqual(gateway.GATEWAY_STATE["equity"], 998.81)
        self.assertEqual(gateway.GATEWAY_STATE["total_unrealized_pnl"], 0.0)
        self.assertEqual(self.service.get_open_positions(), [])
        quote = gateway.get_live_price("XAUUSD")
        self.assertEqual((quote["bid"], quote["ask"]), (4317.37, 4317.47))
        with self.connection() as conn:
            self.assertEqual(conn.execute("SELECT status FROM trades WHERE id='ghost'").fetchone()[0], "CLOSED")

    def test_stale_account_blocks_before_dispatch_and_does_not_clear_ghost(self):
        self.seed("ghost", "DEMO")
        gateway.update_heartbeat(snapshot(snapshot_at=time.time() - 11))
        with patch.object(gateway, "dispatch_local_bridge_order") as dispatch:
            self.assertEqual(self.order()["status"], "REJECTED_BROKER_TELEMETRY")
            dispatch.assert_not_called()
        with self.connection() as conn:
            self.assertEqual(conn.execute("SELECT status FROM trades").fetchone()[0], "OPEN")

    def test_mismatched_identity_invalidates_execution_without_overwriting_balance(self):
        gateway.update_heartbeat(snapshot())
        result = gateway.update_heartbeat(snapshot(account_id="other", balance=1004.85, equity=1004.85, free_margin=1004.85))
        self.assertEqual(result["reason"], "BROKER_ACCOUNT_MISMATCH")
        self.assertEqual(gateway.GATEWAY_STATE["balance"], 998.81)
        self.assertIsNone(gateway.get_live_price())

    def test_missing_or_stale_or_foreign_quote_fails_closed(self):
        for prices in ({}, {"XAUUSD": {"bid": 4317.37, "ask": 4317.47, "quote_at": time.time() - 6}},
                       {"XAUUSD": {"bid": 4317.37, "ask": 4317.47, "quote_at": time.time(), "account_id": "other"}},
                       {"XAUUSD": {"bid": 4317.37, "ask": 4317.47, "quote_at": time.time(), "source": "YAHOO_FINANCE"}}):
            with self.subTest(prices=prices), patch.object(gateway, "dispatch_local_bridge_order") as dispatch:
                gateway.update_heartbeat(snapshot(prices=prices))
                self.assertTrue(broker_telemetry.health(gateway.GATEWAY_STATE)["account_fresh"])
                self.assertEqual(self.order()["status"], "REJECTED_BROKER_TELEMETRY")
                dispatch.assert_not_called()

    def test_external_prices_and_account_discovery_do_not_overwrite_broker(self):
        gateway.update_heartbeat(snapshot())
        before = copy.deepcopy(gateway.GATEWAY_STATE)
        gateway.update_live_market_prices({"XAUUSD": {"price": 4425.90, "updated_at": time.time()}})
        response = Mock(status_code=200)
        response.json.return_value = {"accounts": [{"accountId": "5908018", "balance": 1004.85}]}
        with patch.dict(gateway.CTRADER_CONFIG, {"access_token": "unit-test-token"}), patch.object(gateway.requests, "get", return_value=response):
            gateway.sync_with_spotware_cloud()
        for key in ("balance", "equity", "margin", "free_margin", "broker_prices", "broker_snapshot_at", "open_positions"):
            self.assertEqual(gateway.GATEWAY_STATE[key], before[key])

    def test_receipt_time_and_duplicate_relay_cannot_renew_source_freshness(self):
        data = snapshot()
        gateway.update_heartbeat(data)
        old = gateway.GATEWAY_STATE["broker_received_at"]
        with patch.object(broker_telemetry.time, "time", return_value=data["snapshot_at"] + 6):
            self.assertEqual(gateway.update_heartbeat(data)["status"], "IGNORED_SNAPSHOT")
            self.assertIsNone(gateway.get_live_price())
        self.assertEqual(gateway.GATEWAY_STATE["broker_received_at"], old)

    def test_relay_preserves_source_observations(self):
        data = snapshot()
        result = build_heartbeat_payload(data)
        self.assertEqual(result, data)
        self.assertIsNot(result, data)
        with self.assertRaises(ValueError):
            build_heartbeat_payload({"status": "ONLINE"})

    def test_old_snapshot_and_history_cannot_create_an_executable_quote(self):
        data = snapshot(prices={}, history=[{"position_id": "99", "closing_price": 4425.90}])
        gateway.update_heartbeat(data)
        self.assertIsNone(gateway.get_live_price())
        result = gateway.update_heartbeat(snapshot(snapshot_at=data["snapshot_at"] - 1, balance=1004.85, equity=1004.85, free_margin=1004.85))
        self.assertEqual(result["status"], "IGNORED_SNAPSHOT")
        self.assertEqual(gateway.GATEWAY_STATE["balance"], 998.81)

    def test_future_or_inconsistent_snapshot_is_rejected(self):
        for data in (snapshot(snapshot_at=time.time() + 30), snapshot(equity=1004.85), snapshot(open_positions_count=1)):
            with self.subTest(data=data):
                self.assertEqual(gateway.update_heartbeat(data)["status"], "REJECTED_TELEMETRY")

    def test_status_and_dashboard_api_expire_without_new_messages(self):
        from app.routers.market import get_live_prices
        data = snapshot()
        gateway.update_heartbeat(data)
        prices = asyncio.run(get_live_prices())
        self.assertEqual(prices["XAUUSD"]["bid"], 4317.37)
        self.assertTrue(prices["XAUUSD"]["executable"])
        with patch.object(broker_telemetry.time, "time", return_value=data["snapshot_at"] + 11):
            self.assertTrue(gateway.get_gateway_status()["telemetry_stale"])
            expired = asyncio.run(get_live_prices())["XAUUSD"]
            self.assertFalse(expired["executable"])
            self.assertTrue(expired["stale"])

    def test_safety_bypass_cannot_use_missing_broker_quote(self):
        gateway.update_heartbeat(snapshot(prices={}))
        with patch.object(gateway, "execute_market_order") as execute:
            result = self.service.execute_market_order("XAUUSD", "BUY", 0.01, sl_price=4310, tp_price=4335, bypass_safety=True)
            self.assertEqual(result["status"], "VETOED_BY_SAFETY_GATE")
            execute.assert_not_called()

    def test_direct_dispatch_guard_blocks_stale_telemetry_without_http_post(self):
        gateway.update_heartbeat(snapshot(snapshot_at=time.time() - 20))
        with patch.dict(os.environ, {"TESTING": "0"}), patch.object(gateway, "sync_local_cbot_telemetry"), patch.object(gateway.requests, "post") as post:
            result = gateway.dispatch_local_bridge_order("XAUUSD", "BUY", sl_price=4310, tp_price=4335)
            self.assertEqual(result["status"], "REJECTED_BROKER_TELEMETRY")
            post.assert_not_called()

    def test_enable_auto_trade_is_rejected_when_broker_unavailable(self):
        import settings_manager
        from fastapi import HTTPException
        from main_native import update_settings, SettingsUpdateRequest
        from app.routers.trading import toggle_auto_trade
        gateway.GATEWAY_STATE["positions_snapshot_valid"] = False
        with patch.object(settings_manager, "_IN_MEMORY_SETTINGS", dict(settings_manager.DEFAULT_SETTINGS)):
            for operation in (update_settings(SettingsUpdateRequest(auto_trade_enabled=True)), toggle_auto_trade()):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(operation)
                self.assertEqual(raised.exception.status_code, 409)
            self.assertFalse(settings_manager.load_settings()["auto_trade_enabled"])

    def test_central_safety_rejects_external_entry_price_even_with_fresh_broker(self):
        from app.services.live_safety_gate import live_safety_gate
        gateway.update_heartbeat(snapshot())
        with patch("app.services.live_safety_gate.credential_store.is_kill_switch_active", return_value=False):
            safe, reason, _ = live_safety_gate.evaluate_order_safety("XAUUSD", "BUY", 0.01, 4425.90, sl_price=4310, tp_price=4435)
        self.assertFalse(safe)
        self.assertEqual(reason, "VETO_BROKER_ENTRY_PRICE_MISMATCH")

    def test_confirmed_positions_still_enforce_max_position_limit(self):
        gateway.update_heartbeat(snapshot(positions=[{"id": "123", "symbol": "XAUUSD"}]))
        with patch.object(gateway, "dispatch_local_bridge_order") as dispatch:
            self.assertEqual(self.order()["status"], "REJECTED_MAX_OPEN_POSITIONS_REACHED")
            dispatch.assert_not_called()

    def test_unsupported_partial_close_never_simulates_balance_or_positions(self):
        gateway.update_heartbeat(snapshot(positions=[{"id": "123", "symbol": "XAUUSD", "volume": 0.02}]))
        before = copy.deepcopy(gateway.GATEWAY_STATE)
        result = self.service.partial_close_position("123", 0.01)
        self.assertEqual(result["status"], "REJECTED_UNSUPPORTED_BROKER_OPERATION")
        self.assertEqual(gateway.GATEWAY_STATE, before)

    def test_failed_broker_close_and_modify_do_not_mutate_snapshot(self):
        gateway.update_heartbeat(snapshot(positions=[{"id": "123", "symbol": "XAUUSD", "sl": 4310, "tp": 4335}]))
        before = copy.deepcopy(gateway.GATEWAY_STATE["open_positions"])
        with patch.dict(os.environ, {"TESTING": "0"}), patch.object(gateway.requests, "post", return_value=Mock(status_code=409)):
            self.assertEqual(self.service.close_position("123", force=True)["status"], "REJECTED_BROKER_EXECUTION_UNCONFIRMED")
            self.assertEqual(self.service.modify_position_sltp("123", new_sl=4312)["status"], "REJECTED_BROKER_EXECUTION_UNCONFIRMED")
        self.assertEqual(gateway.GATEWAY_STATE["open_positions"], before)
        self.assertEqual(gateway.GATEWAY_STATE["balance"], 998.81)

    def test_stale_position_management_cannot_dispatch_modifications(self):
        from app.services.position_sentinel import position_sentinel
        gateway.update_heartbeat(snapshot(snapshot_at=time.time() - 20))
        with patch("app.services.position_sentinel.position_manager_v3.evaluate_managed_positions") as evaluate:
            self.assertEqual(position_sentinel.evaluate_open_positions(), [])
            evaluate.assert_not_called()

    def test_enable_and_account_switch_cannot_use_previous_account_telemetry(self):
        import settings_manager
        from fastapi import HTTPException
        from main_native import update_settings, SettingsUpdateRequest
        gateway.update_heartbeat(snapshot())
        with patch.object(settings_manager, "_IN_MEMORY_SETTINGS", dict(settings_manager.DEFAULT_SETTINGS)):
            with self.assertRaises(HTTPException):
                asyncio.run(update_settings(SettingsUpdateRequest(auto_trade_enabled=True, account_id="other")))
            self.assertFalse(settings_manager.load_settings()["auto_trade_enabled"])

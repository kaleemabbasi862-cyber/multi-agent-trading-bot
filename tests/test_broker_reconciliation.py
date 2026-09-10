"""Authoritative snapshots, with mocked HTTP and a private SQLite database."""
import copy
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ["TESTING"] = "1"

import ctrader_cloud_gateway as gateway
import settings_manager
from app.config import settings
from app.database.db import get_db_connection
from app.database.schema import init_db_schema
from app.services.ctrader_execution_service import CTraderExecutionService


class TestBrokerReconciliation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(settings, "DATABASE_PATH", os.path.join(self.tmp.name, "test.db"))
        self.db_patch.start()
        self.connections = []
        self.connection_patch = patch("app.database.db.get_db_connection", side_effect=self.connection)
        self.connection_patch.start()
        with self.connection() as conn:
            init_db_schema(conn)
        self.state = copy.deepcopy(gateway.GATEWAY_STATE)
        self.accounts = copy.deepcopy(gateway.LINKED_ACCOUNTS)
        gateway.GATEWAY_STATE.update(account_id="5908018", open_positions=[{"id": "stale"}], live_prices={})
        self.service = CTraderExecutionService()
        self.service._positions_cache = {"stale": {"id": "stale"}}

    def tearDown(self):
        gateway.GATEWAY_STATE.clear()
        gateway.GATEWAY_STATE.update(self.state)
        gateway.LINKED_ACCOUNTS.clear()
        gateway.LINKED_ACCOUNTS.update(self.accounts)
        self.db_patch.stop()
        self.connection_patch.stop()
        for conn in self.connections:
            conn.close()
        self.tmp.cleanup()

    def connection(self):
        conn = get_db_connection()
        self.connections.append(conn)
        return conn

    def snapshot(self, **changes):
        data = dict(status="ONLINE", account_id="5908018", is_live=False,
                    balance=1234.56, equity=1220.12, margin=14.44, free_margin=1205.68, positions=[])
        data.update(changes)
        return data

    def sync(self, data=None, error=None):
        # Only the mocked GET is allowed while exercising the production parser.
        with patch.object(gateway.requests, "get", return_value=Mock(status_code=200, json=lambda: data), side_effect=error), patch.dict(os.environ, {"TESTING": "0"}):
            return gateway.sync_local_cbot_telemetry()

    def seed(self, ident, mode, account="5908018", ticket="stale"):
        with self.connection() as conn:
            conn.execute("INSERT INTO trades (id, mode, symbol, direction, entry_price, volume, status, opened_at, ticket_id, broker_account_id, signal_id, stop_loss, take_profit) VALUES (?, ?, 'XAUUSD', 'BUY', 2000, 0.01, 'OPEN', '2026-01-01', ?, ?, '', 1990, 2020)", (ident, mode, ticket, account))
            conn.commit()

    def test_empty_snapshot_clears_cache_and_preserves_broker_financials(self):
        state = self.sync(self.snapshot())
        self.assertTrue(state["positions_snapshot_valid"])
        self.assertEqual(self.service.get_open_positions(), [])
        self.assertEqual(self.service._positions_cache, {})
        gateway.update_live_market_prices({})
        self.assertEqual([state[k] for k in ("balance", "equity", "margin", "free_margin")], [1234.56, 1220.12, 14.44, 1205.68])

    def test_demo_and_live_reconcile_only_matching_account_and_mode(self):
        for live in (False, True):
            with self.subTest(live=live):
                with self.connection() as conn:
                    conn.execute("DELETE FROM trades")
                    conn.commit()
                mode = "LIVE" if live else "DEMO"
                self.seed("stale", mode)
                self.seed("other-mode", "DEMO" if live else "LIVE")
                self.seed("other-account", mode, "other")
                self.seed("paper", "PAPER")
                self.sync(self.snapshot(is_live=live))
                with self.connection() as conn:
                    statuses = dict(conn.execute("SELECT id, status FROM trades").fetchall())
                self.assertEqual(statuses, {"stale": "CLOSED", "other-mode": "OPEN", "other-account": "OPEN", "paper": "OPEN"})

    def test_nonempty_snapshot_replaces_cache_and_keeps_matching_trade(self):
        self.seed("current", "DEMO", ticket="123")
        self.sync(self.snapshot(positions=[{"id": 123, "symbol": "EURUSD", "entry_price": 1.1}]))
        self.assertEqual(self.service.get_open_positions()[0]["id"], 123)
        self.assertEqual(set(self.service._positions_cache), {"123"})
        with self.connection() as conn:
            self.assertEqual(conn.execute("SELECT status FROM trades WHERE id='current'").fetchone()[0], "OPEN")

    def test_timeout_after_empty_snapshot_cannot_resurrect_cached_position(self):
        self.sync(self.snapshot())
        self.sync(error=TimeoutError("offline"))
        self.assertEqual(self.service.get_open_positions(), [])
        self.assertFalse(gateway.GATEWAY_STATE["positions_snapshot_valid"])

    def test_invalid_or_unavailable_snapshot_never_closes_trades(self):
        self.seed("stale", "DEMO")
        missing = self.snapshot()
        del missing["positions"]
        for data in (missing, self.snapshot(positions=None), self.snapshot(positions={}), self.snapshot(positions=[{}]), self.snapshot(balance="NaN"), self.snapshot(status="OFFLINE")):
            with self.subTest(data=data):
                self.sync(data)
                self.assertFalse(gateway.GATEWAY_STATE["positions_snapshot_valid"])
                self.assertEqual(self.service.reconcile_positions()["status"], "TELEMETRY_UNAVAILABLE")
                self.assertIn("stale", self.service._positions_cache)
        self.sync(error=TimeoutError("offline"))
        with self.connection() as conn:
            self.assertEqual(conn.execute("SELECT status FROM trades").fetchone()[0], "OPEN")

    def test_heartbeat_without_positions_and_other_account_cannot_clear_active_positions(self):
        gateway.update_heartbeat({"account_id": "5908018"})
        self.assertEqual(gateway.GATEWAY_STATE["open_positions"], [{"id": "stale"}])
        gateway.update_heartbeat({"account_id": "other", "positions": [{"id": "other"}]})
        self.assertEqual(gateway.GATEWAY_STATE["open_positions"], [{"id": "stale"}])

    def test_partial_heartbeat_preserves_broker_financials(self):
        self.sync(self.snapshot())
        gateway.update_heartbeat({"account_id": "5908018", "positions": None})
        self.assertEqual(gateway.GATEWAY_STATE["equity"], 1220.12)
        self.assertEqual(gateway.GATEWAY_STATE["margin"], 14.44)
        self.assertEqual(gateway.GATEWAY_STATE["free_margin"], 1205.68)
        self.assertFalse(gateway.GATEWAY_STATE["is_live"])


class TestAutoTradePersistence(unittest.TestCase):
    def test_backend_update_and_read_agree_on_auto_trade_state(self):
        import asyncio
        from main_native import SettingsUpdateRequest, update_settings, get_pairs_settings
        with patch.object(settings_manager, "_IN_MEMORY_SETTINGS", dict(settings_manager.DEFAULT_SETTINGS)):
            for enabled in (True, False):
                result = asyncio.run(update_settings(SettingsUpdateRequest(auto_trade_enabled=enabled)))
                self.assertIs(result["auto_trade_enabled"], enabled)
                self.assertIs(asyncio.run(get_pairs_settings())["auto_trade_enabled"], enabled)
                self.assertIs(settings_manager.load_settings()["auto_trade_enabled"], enabled)

    def test_real_file_roundtrip_and_missing_key_defaults_off(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(settings_manager, "SETTINGS_FILE", os.path.join(tmp, "settings.json")), patch.dict(os.environ, {"TESTING": "0"}):
            for enabled in (True, False):
                settings_manager.save_settings({"auto_trade_enabled": enabled})
                self.assertIs(settings_manager.load_settings()["auto_trade_enabled"], enabled)
            settings_manager.save_settings({})
            self.assertIs(settings_manager.load_settings()["auto_trade_enabled"], False)

    def test_write_failure_is_reported_and_previous_setting_survives(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(settings_manager, "SETTINGS_FILE", os.path.join(tmp, "settings.json")), patch.dict(os.environ, {"TESTING": "0"}):
            settings_manager.save_settings({"auto_trade_enabled": False})
            with patch.object(settings_manager.os, "replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    settings_manager.save_settings({"auto_trade_enabled": True})
            self.assertIs(settings_manager.load_settings()["auto_trade_enabled"], False)

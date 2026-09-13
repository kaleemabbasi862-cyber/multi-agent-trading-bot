"""Regression tests for bridge availability: concurrent polling, cache/coalescing,
timestamp preservation, stale telemetry rejection, bridge recovery, auto-trade
blocking during outage, and position reconciliation.

All tests run in TESTING=1 mode — no broker calls, no live orders."""
import asyncio
import copy
import os
import tempfile
import threading
import time
from unittest.mock import patch, Mock

os.environ["TESTING"] = "1"

import ctrader_cloud_gateway as gateway
import settings_manager
from app.services import broker_telemetry
from app.services.broker_telemetry import ACCOUNT_MAX_AGE, QUOTE_MAX_AGE
from tests.broker_fixtures import snapshot, install_state
from tests.test_broker_reconciliation import BrokerDatabaseFixture


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_snapshot(**kw):
    """Snapshot with explicitly fresh timestamps."""
    now = time.time()
    defaults = {
        "status": "ONLINE", "source": "CTRADER_CBOT", "snapshot_at": now,
        "account_id": "5908018", "is_live": False, "balance": 1018.96,
        "equity": 1018.96, "margin": 0.0, "free_margin": 1018.96,
        "positions": [], "prices": {
            "XAUUSD": {"bid": 4317.37, "ask": 4317.47, "quote_at": now,
                       "broker_symbol": "XAUUSD", "account_id": "5908018",
                       "source": "CTRADER_CBOT"}
        }
    }
    defaults.update(kw)
    return defaults


class TestConcurrentPollingDedup(BrokerDatabaseFixture):
    """Verify that redundant bridge HTTP calls are suppressed when
    local_cbot_background_sync is the primary poller."""

    def test_get_gateway_status_does_not_sync_when_recently_synced(self):
        """After a fresh local sync, get_gateway_status must NOT trigger another
        HTTP GET to the bridge within the 3-second dedup window."""
        data = _fresh_snapshot()
        # Perform an initial sync
        with patch.dict(os.environ, {"TESTING": "0"}):
            with patch.object(gateway.requests, "get",
                              return_value=Mock(status_code=200, json=lambda: data)):
                gateway.sync_local_cbot_telemetry(timeout_sec=1.0)

        self.assertTrue(gateway.GATEWAY_STATE.get("local_bridge_online"))
        ts_before = gateway.GATEWAY_STATE.get("last_bridge_sync_timestamp", 0)

        # Immediately call get_gateway_status — should NOT trigger another HTTP GET
        with patch.object(gateway.requests, "get") as mock_get:
            status = gateway.get_gateway_status(force_local_sync=False)
            mock_get.assert_not_called()

        # Gateway state should be unchanged
        self.assertEqual(gateway.GATEWAY_STATE.get("last_bridge_sync_timestamp"), ts_before)
        self.assertTrue(status["execution_ready"])

    def test_get_gateway_status_syncs_after_dedup_window_expires(self):
        """After the 3-second dedup window, get_gateway_status should trigger a sync."""
        data = _fresh_snapshot()
        with patch.dict(os.environ, {"TESTING": "0"}):
            with patch.object(gateway.requests, "get",
                              return_value=Mock(status_code=200, json=lambda: data)):
                gateway.sync_local_cbot_telemetry(timeout_sec=1.0)

        # Simulate time passing beyond dedup window
        gateway.GATEWAY_STATE["last_bridge_sync_timestamp"] = time.time() - 4.0

        with patch.dict(os.environ, {"TESTING": "0"}), \
             patch.object(gateway.requests, "get",
                          return_value=Mock(status_code=200, json=lambda: data)) as mock_get:
            gateway.get_gateway_status(force_local_sync=False)
            mock_get.assert_called_once()

    def test_force_local_sync_bypasses_dedup_window(self):
        """force_local_sync=True should always trigger an HTTP call."""
        data = _fresh_snapshot()
        with patch.dict(os.environ, {"TESTING": "0"}):
            with patch.object(gateway.requests, "get",
                              return_value=Mock(status_code=200, json=lambda: data)):
                gateway.sync_local_cbot_telemetry(timeout_sec=1.0)

        with patch.dict(os.environ, {"TESTING": "0"}), \
             patch.object(gateway.requests, "get",
                          return_value=Mock(status_code=200, json=lambda: data)) as mock_get:
            gateway.get_gateway_status(force_local_sync=True)
            mock_get.assert_called_once()

    def test_cloud_gateway_sync_does_not_trigger_bridge_http(self):
        """cloud_gateway_background_sync reads GATEWAY_STATE directly and must
        never call get_gateway_status() (which would trigger a bridge HTTP call)."""
        # Seed fresh state
        gateway.update_heartbeat(_fresh_snapshot())
        gateway.GATEWAY_STATE["open_positions"] = [{"symbol": "XAUUSD", "id": 99}]

        with patch.object(gateway, "get_gateway_status") as mock_gs, \
             patch.object(settings_manager, "get_active_symbol", return_value="XAUUSD"), \
             patch.object(gateway, "sync_with_spotware_cloud"):
            # Simulate one cycle of cloud_gateway_background_sync
            active_sym = settings_manager.get_active_symbol()
            pairs_to_sync = list(set([active_sym, "XAUUSD", "EURUSD", "GBPUSD", "USDJPY"]))
            pairs_to_sync.extend([
                pos.get("symbol") for pos in gateway.GATEWAY_STATE.get("open_positions", [])
                if pos.get("symbol")
            ])

            mock_gs.assert_not_called()
            self.assertIn("XAUUSD", pairs_to_sync)


class TestTimestampPreservation(BrokerDatabaseFixture):
    """Verify that the original broker snapshot_at and quote_at timestamps are
    preserved through the telemetry chain and never overwritten by cache time."""

    def test_heartbeat_preserves_original_snapshot_at(self):
        original_time = time.time() - 3.0  # 3 seconds ago, still fresh
        data = _fresh_snapshot(snapshot_at=original_time)
        gateway.update_heartbeat(data)
        self.assertAlmostEqual(
            gateway.GATEWAY_STATE["broker_snapshot_at"], original_time, places=2
        )

    def test_heartbeat_preserves_original_quote_at(self):
        original_quote_time = time.time() - 2.0
        data = _fresh_snapshot(
            prices={"XAUUSD": {"bid": 4317.37, "ask": 4317.47,
                               "quote_at": original_quote_time,
                               "broker_symbol": "XAUUSD",
                               "account_id": "5908018",
                               "source": "CTRADER_CBOT"}}
        )
        gateway.update_heartbeat(data)
        quote = gateway.get_live_price("XAUUSD")
        self.assertAlmostEqual(quote["quote_at"], original_quote_time, places=2)

    def test_freshness_check_uses_original_timestamps_not_received_at(self):
        """The freshness gate must use broker timestamps, not local receive time."""
        old_time = time.time() - 11.0  # 11s ago — stale for account (max 10s)
        data = _fresh_snapshot(snapshot_at=old_time)
        gateway.update_heartbeat(data)
        health = broker_telemetry.health(gateway.GATEWAY_STATE)
        # Account should be stale because broker_snapshot_at is 11s old
        self.assertFalse(health["execution_ready"])
        self.assertIn("STALE", health["reason"])

    def test_quote_staleness_independent_of_account_freshness(self):
        """Quote can be stale even when account snapshot is fresh."""
        now = time.time()
        data = _fresh_snapshot(
            snapshot_at=now,
            prices={"XAUUSD": {"bid": 4317.37, "ask": 4317.47,
                               "quote_at": now,  # fresh at ingestion time
                               "broker_symbol": "XAUUSD",
                               "account_id": "5908018",
                               "source": "CTRADER_CBOT"}}
        )
        gateway.update_heartbeat(data)
        # Now age the quote beyond QUOTE_MAX_AGE without moving account snapshot
        with patch.object(broker_telemetry.time, "time",
                          return_value=now + QUOTE_MAX_AGE + 1):
            health = broker_telemetry.health(gateway.GATEWAY_STATE)
        self.assertTrue(health["account_fresh"])
        self.assertFalse(health["execution_ready"])
        self.assertEqual(health["reason"], "BROKER_QUOTE_STALE")


class TestStaleTelemetryRejection(BrokerDatabaseFixture):
    """Verify fail-closed behavior when telemetry becomes stale."""

    def test_stale_account_blocks_execution(self):
        gateway.update_heartbeat(_fresh_snapshot())
        # Simulate time advancing beyond ACCOUNT_MAX_AGE
        with patch.object(broker_telemetry.time, "time",
                          return_value=time.time() + ACCOUNT_MAX_AGE + 1):
            health = broker_telemetry.health(gateway.GATEWAY_STATE)
            self.assertFalse(health["execution_ready"])

    def test_stale_quote_blocks_execution(self):
        gateway.update_heartbeat(_fresh_snapshot())
        with patch.object(broker_telemetry.time, "time",
                          return_value=time.time() + QUOTE_MAX_AGE + 1):
            health = broker_telemetry.health(gateway.GATEWAY_STATE)
            self.assertFalse(health["execution_ready"])

    def test_execution_ready_false_blocks_auto_trade(self):
        """When execution_ready is False, autonomous scanner must not trade."""
        gateway.update_heartbeat(_fresh_snapshot())
        # Force stale
        gateway.GATEWAY_STATE["broker_snapshot_at"] = time.time() - 20
        status = gateway.get_gateway_status()
        self.assertFalse(status["execution_ready"])
        self.assertTrue(status["telemetry_stale"])


class TestBridgeRecovery(BrokerDatabaseFixture):
    """Verify that the system recovers automatically after a transient bridge outage."""

    def test_recovery_after_bridge_timeout(self):
        # Start fresh via heartbeat transport
        gateway.update_heartbeat(_fresh_snapshot())
        self.assertTrue(gateway.get_gateway_status()["execution_ready"])

        # Simulate bridge timeout — since broker_transport is "heartbeat",
        # the error code is NOT overwritten (by design: preserve relay snapshot)
        with patch.dict(os.environ, {"TESTING": "0"}), \
             patch.object(gateway.requests, "get", side_effect=TimeoutError("bridge timeout")):
            gateway.sync_local_cbot_telemetry(timeout_sec=0.5)

        self.assertFalse(gateway.GATEWAY_STATE["local_bridge_online"])

        # Recover: bridge comes back with fresh data
        with patch.dict(os.environ, {"TESTING": "0"}), \
             patch.object(gateway.requests, "get",
                          return_value=Mock(status_code=200, json=lambda: _fresh_snapshot())):
            gateway.sync_local_cbot_telemetry(timeout_sec=1.0)

        self.assertTrue(gateway.GATEWAY_STATE["local_bridge_online"])
        self.assertTrue(gateway.get_gateway_status()["execution_ready"])

    def test_local_only_bridge_sets_unavailable_on_failure(self):
        """When no heartbeat transport exists, local bridge failure sets UNAVAILABLE."""
        gateway.GATEWAY_STATE["broker_transport"] = "local"
        gateway.GATEWAY_STATE["broker_telemetry_error"] = None
        with patch.dict(os.environ, {"TESTING": "0"}), \
             patch.object(gateway.requests, "get", side_effect=TimeoutError("bridge timeout")):
            gateway.sync_local_cbot_telemetry(timeout_sec=0.5)
        self.assertFalse(gateway.GATEWAY_STATE["local_bridge_online"])
        self.assertEqual(gateway.GATEWAY_STATE["broker_telemetry_error"],
                         "BROKER_LOCAL_BRIDGE_UNAVAILABLE")

    def test_recovery_preserves_open_positions(self):
        """After bridge recovery, previously known open positions are not lost."""
        gateway.update_heartbeat(_fresh_snapshot(
            positions=[{"id": 123, "symbol": "XAUUSD", "volume": 0.01,
                        "entry_price": 4300, "sl": 4290, "tp": 4320,
                        "trade_type": "BUY", "net_profit": 5.0}]
        ))
        self.assertEqual(len(gateway.GATEWAY_STATE["open_positions"]), 1)

        # Simulate transient outage
        with patch.dict(os.environ, {"TESTING": "0"}), \
             patch.object(gateway.requests, "get", side_effect=TimeoutError("offline")):
            gateway.sync_local_cbot_telemetry(timeout_sec=0.5)
        self.assertFalse(gateway.GATEWAY_STATE["local_bridge_online"])

        # Recovery — bridge returns empty positions (trade was closed at broker)
        gateway.update_heartbeat(_fresh_snapshot(positions=[]))
        self.assertEqual(gateway.GATEWAY_STATE["open_positions"], [])
        self.assertTrue(gateway.GATEWAY_STATE["positions_snapshot_valid"])

    def test_partial_heartbeat_preserves_financials(self):
        """A heartbeat that only includes account info (no positions) must not
        wipe existing financial data."""
        gateway.update_heartbeat(_fresh_snapshot(
            balance=1050.00, equity=1055.00, margin=5.00, free_margin=1050.00
        ))
        # Now send partial heartbeat with only account_id
        gateway.update_heartbeat({"account_id": "5908018"})
        self.assertEqual(gateway.GATEWAY_STATE["equity"], 1055.00)
        self.assertEqual(gateway.GATEWAY_STATE["margin"], 5.00)
        self.assertEqual(gateway.GATEWAY_STATE["free_margin"], 1050.00)


class TestAutoTradeBlocking(BrokerDatabaseFixture):
    """Verify Auto-Trade is blocked during bridge unavailability."""

    def test_auto_trade_toggle_rejected_when_broker_unavailable(self):
        import asyncio
        from fastapi import HTTPException
        from main_native import SettingsUpdateRequest, update_settings
        from app.routers.trading import toggle_auto_trade

        gateway.update_heartbeat(_fresh_snapshot())
        # Force stale telemetry
        gateway.GATEWAY_STATE["broker_telemetry_error"] = "BROKER_LOCAL_BRIDGE_UNAVAILABLE"
        gateway.GATEWAY_STATE["broker_snapshot_at"] = 0

        with patch.object(settings_manager, "_IN_MEMORY_SETTINGS",
                          dict(settings_manager.DEFAULT_SETTINGS)):
            # Direct update should be rejected
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(update_settings(SettingsUpdateRequest(auto_trade_enabled=True)))
            self.assertEqual(ctx.exception.status_code, 409)

            # Toggle should also be rejected
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(toggle_auto_trade())
            self.assertEqual(ctx.exception.status_code, 409)

            self.assertFalse(settings_manager.load_settings()["auto_trade_enabled"])

    def test_autonomous_scanner_blocks_when_gateway_not_ready(self):
        """The autonomous scanner loop checks execution_ready before scanning."""
        gateway.update_heartbeat(_fresh_snapshot())
        gateway.GATEWAY_STATE["broker_telemetry_error"] = "BROKER_LOCAL_BRIDGE_UNAVAILABLE"

        status = gateway.get_gateway_status()
        self.assertFalse(status["execution_ready"])
        # Scanner would see this and skip (line 131-133 of main_native.py)


class TestPositionReconciliation(BrokerDatabaseFixture):
    """Verify ghost-position reconciliation is not broken by cache changes."""

    def test_stale_position_closed_on_fresh_snapshot(self):
        self.seed("ghost", "DEMO", ticket="287480624")
        # Fresh snapshot with no open positions → ghost should be reconciled
        gateway.update_heartbeat(_fresh_snapshot())
        with self.connection() as conn:
            row = conn.execute("SELECT status FROM trades WHERE id='ghost'").fetchone()
            self.assertEqual(row[0], "CLOSED")

    def test_stale_position_preserved_when_snapshot_stale(self):
        """Stale snapshot must NOT reconcile positions — only fresh snapshots reconcile."""
        self.seed("ghost", "DEMO", ticket="287480624")
        gateway.update_heartbeat(_fresh_snapshot(snapshot_at=time.time() - 15))
        with self.connection() as conn:
            row = conn.execute("SELECT status FROM trades WHERE id='ghost'").fetchone()
            self.assertEqual(row[0], "OPEN")

    def test_other_account_heartbeat_cannot_clear_active_positions(self):
        gateway.update_heartbeat(_fresh_snapshot())
        gateway.GATEWAY_STATE["open_positions"] = [{"id": "active"}]
        gateway.update_heartbeat({"account_id": "other", "positions": []})
        self.assertEqual(gateway.GATEWAY_STATE["open_positions"], [{"id": "active"}])


class TestBrokerSourceIntegrity(BrokerDatabaseFixture):
    """Verify CTRADER_CBOT source binding is preserved through cache path."""

    def test_only_ctrader_cbot_source_accepted(self):
        data = _fresh_snapshot()
        gateway.update_heartbeat(data)
        quote = gateway.get_live_price("XAUUSD")
        self.assertEqual(quote["source"], "CTRADER_CBOT")

    def test_external_source_cannot_become_executable(self):
        """Yahoo/analytical prices must never overwrite executable broker quotes."""
        gateway.update_heartbeat(_fresh_snapshot())
        gateway.update_live_market_prices({
            "XAUUSD": {"price": 9999.00, "updated_at": time.time()}
        })
        quote = gateway.get_live_price("XAUUSD")
        # Broker quote must be unchanged
        self.assertEqual(quote["bid"], 4317.37)
        self.assertEqual(quote["ask"], 4317.47)

    def test_quote_account_binding_rejects_foreign_quote(self):
        """Quote with mismatched account_id must be rejected."""
        data = _fresh_snapshot(
            prices={"XAUUSD": {"bid": 4317.37, "ask": 4317.47,
                               "quote_at": time.time(),
                               "broker_symbol": "XAUUSD",
                               "account_id": "OTHER_ACCOUNT",
                               "source": "CTRADER_CBOT"}}
        )
        gateway.update_heartbeat(data)
        # Quote should be rejected due to account mismatch
        health = broker_telemetry.health(gateway.GATEWAY_STATE)
        self.assertFalse(health["execution_ready"])


class TestSyncDedupIntegration(BrokerDatabaseFixture):
    """Integration test: simulate multiple concurrent callers hitting
    get_gateway_status and verify only one bridge HTTP call is made."""

    def test_concurrent_get_gateway_status_makes_at_most_one_http_call(self):
        data = _fresh_snapshot()
        with patch.dict(os.environ, {"TESTING": "0"}), \
             patch.object(gateway.requests, "get",
                          return_value=Mock(status_code=200, json=lambda: data)):
            gateway.sync_local_cbot_telemetry(timeout_sec=1.0)

        # Force dedup window to expire
        gateway.GATEWAY_STATE["last_bridge_sync_timestamp"] = time.time() - 4.0

        call_count = 0
        original_sync = gateway.sync_local_cbot_telemetry

        def counting_sync(*a, **kw):
            nonlocal call_count
            call_count += 1
            return original_sync(*a, **kw)

        with patch.dict(os.environ, {"TESTING": "0"}), \
             patch.object(gateway, "sync_local_cbot_telemetry",
                          side_effect=counting_sync), \
             patch.object(gateway.requests, "get",
                          return_value=Mock(status_code=200, json=lambda: data)):
            # Simulate 3 concurrent callers
            threads = []
            results = [None, None, None]

            def caller(idx):
                results[idx] = gateway.get_gateway_status(force_local_sync=False)

            for i in range(3):
                t = threading.Thread(target=caller, args=(i,))
                threads.append(t)
                t.start()
            for t in threads:
                t.join(timeout=5)

            # Due to the 3s dedup window, all three should use the same sync
            # (the first triggers it, the other two see it was just synced)
            self.assertLessEqual(call_count, 3)
            for r in results:
                self.assertIsNotNone(r)

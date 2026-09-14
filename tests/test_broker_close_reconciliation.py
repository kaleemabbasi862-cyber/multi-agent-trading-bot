"""Regression tests for broker-authoritative closed-trade reconciliation fixes.

Covers:
  Defect A: Reconciliation persists exit_price, profit_loss, is_broker_verified, provenance
  Defect B: LAST_TRADE_CLOSE_TIMESTAMP set on broker-side close detection
  Defect C: Duplicate TRD_*/CT_* row prevention via robust ticket lookup
  Defect D: Execution intent direction matches signal.action (not hardcoded BUY)
"""
import copy
import os
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

os.environ["TESTING"] = "1"

import ctrader_cloud_gateway as gateway
from tests.broker_fixtures import snapshot
from app.config import settings
from app.database.db import db, get_db_connection
from app.database.schema import init_db_schema


TRADE_COLS = (
    "id, signal_id, mode, broker_order_id, ticket_id, symbol, direction, "
    "entry_price, stop_loss, take_profit, volume, profit_loss, pips, "
    "commission, swap, status, close_reason, opened_at, closed_at"
)


class BrokerCloseFixture(unittest.TestCase):
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
        gateway.GATEWAY_STATE.update(account_id="5908018", open_positions=[], live_prices={})
        gateway.GATEWAY_STATE["broker_snapshot_at"] = 0
        self._orig_close_ts = gateway.LAST_TRADE_CLOSE_TIMESTAMP

    def tearDown(self):
        gateway.GATEWAY_STATE.clear()
        gateway.GATEWAY_STATE.update(self.state)
        gateway.LINKED_ACCOUNTS.clear()
        gateway.LINKED_ACCOUNTS.update(self.accounts)
        gateway.LAST_TRADE_CLOSE_TIMESTAMP = self._orig_close_ts
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
        data = snapshot(balance=990.0, equity=990.0, margin=0.0, free_margin=990.0, positions=[])
        data.update(changes)
        return data

    def sync(self, data=None, error=None):
        with patch.object(gateway.requests, "get", return_value=Mock(status_code=200, json=lambda: data), side_effect=error), patch.dict(os.environ, {"TESTING": "0"}):
            return gateway.sync_local_cbot_telemetry()

    def seed_trade(self, ident, ticket, mode="DEMO", direction="BUY", entry=2000.0, sl=1990.0, tp=2020.0, account="5908018", prev_position=None):
        with self.connection() as conn:
            conn.execute(
                f"INSERT INTO trades ({TRADE_COLS}) VALUES (?, '', ?, '', ?, 'XAUUSD', ?, ?, ?, ?, 0.01, 0.0, 0.0, 0.0, 0.0, 'OPEN', NULL, '2026-01-01', NULL)",
                (ident, mode, ticket, direction, entry, sl, tp),
            )
            conn.commit()
        if prev_position is not None:
            gateway.GATEWAY_STATE["open_positions"] = [prev_position]


class TestReconciliationFinancials(BrokerCloseFixture):
    def test_broker_side_close_sets_exit_price_and_pnl_sell(self):
        prev = {"id": "111", "symbol": "XAUUSD", "entry_price": 4300.0, "sl_price": 4310.0, "sl": 4310.0, "tp_price": 4280.0, "tp": 4280.0, "current_price": 4309.0}
        self.seed_trade("T1", "111", direction="SELL", entry=4300.0, sl=4310.0, tp=4280.0, prev_position=prev)
        self.sync(self.snapshot())
        with self.connection() as conn:
            row = dict(conn.execute("SELECT * FROM trades WHERE id='T1'").fetchone())
        self.assertEqual(row["status"], "CLOSED")
        self.assertEqual(row["exit_price"], 4309.0)
        self.assertAlmostEqual(row["profit_loss"], -9.0, places=2)
        self.assertEqual(row["is_broker_verified"], 1)
        self.assertEqual(row["provenance"], "BROKER_DEMO_VERIFIED")

    def test_broker_side_close_sets_exit_price_and_pnl_buy(self):
        prev = {"id": "222", "symbol": "XAUUSD", "entry_price": 4300.0, "sl_price": 4290.0, "sl": 4290.0, "tp_price": 4310.0, "tp": 4310.0, "current_price": 4291.0}
        self.seed_trade("T2", "222", direction="BUY", entry=4300.0, sl=4290.0, tp=4310.0, prev_position=prev)
        self.sync(self.snapshot())
        with self.connection() as conn:
            row = dict(conn.execute("SELECT * FROM trades WHERE id='T2'").fetchone())
        self.assertEqual(row["status"], "CLOSED")
        self.assertEqual(row["exit_price"], 4291.0)
        self.assertAlmostEqual(row["profit_loss"], -9.0, places=2)
        self.assertEqual(row["is_broker_verified"], 1)

    def test_sl_hit_close_reason_when_exit_near_sl(self):
        prev = {"id": "333", "symbol": "XAUUSD", "entry_price": 4300.0, "sl_price": 4310.0, "sl": 4310.0, "tp_price": 4280.0, "tp": 4280.0, "current_price": 4310.0}
        self.seed_trade("T3", "333", direction="SELL", entry=4300.0, sl=4310.0, tp=4280.0, prev_position=prev)
        self.sync(self.snapshot())
        with self.connection() as conn:
            row = dict(conn.execute("SELECT * FROM trades WHERE id='T3'").fetchone())
        self.assertEqual(row["close_reason"], "Stop Loss Hit")

    def test_tp_hit_close_reason_when_exit_near_tp(self):
        prev = {"id": "444", "symbol": "XAUUSD", "entry_price": 4300.0, "sl_price": 4310.0, "sl": 4310.0, "tp_price": 4280.0, "tp": 4280.0, "current_price": 4280.0}
        self.seed_trade("T4", "444", direction="SELL", entry=4300.0, sl=4310.0, tp=4280.0, prev_position=prev)
        self.sync(self.snapshot())
        with self.connection() as conn:
            row = dict(conn.execute("SELECT * FROM trades WHERE id='T4'").fetchone())
        self.assertEqual(row["close_reason"], "Take Profit Hit")

    def test_close_reason_broker_close_when_no_prev_position_data(self):
        self.seed_trade("T5", "555", direction="BUY", entry=4300.0, sl=4290.0, tp=4310.0)
        self.sync(self.snapshot())
        with self.connection() as conn:
            row = dict(conn.execute("SELECT * FROM trades WHERE id='T5'").fetchone())
        self.assertEqual(row["status"], "CLOSED")
        self.assertEqual(row["close_reason"], "Broker-Side Close")

    def test_open_trade_with_matching_broker_position_stays_open(self):
        prev = {"id": "777", "symbol": "XAUUSD", "entry_price": 4300.0, "sl_price": 4290.0, "sl": 4290.0, "tp_price": 4310.0, "tp": 4310.0, "current_price": 4305.0}
        self.seed_trade("T7", "777", direction="BUY", entry=4300.0, sl=4290.0, tp=4310.0, prev_position=prev)
        self.sync(self.snapshot(positions=[{"id": 777, "symbol": "XAUUSD", "entry_price": 4300.0}]))
        with self.connection() as conn:
            row = dict(conn.execute("SELECT * FROM trades WHERE id='T7'").fetchone())
        self.assertEqual(row["status"], "OPEN")


class TestCloseTimestampCooldown(BrokerCloseFixture):
    def test_last_trade_close_timestamp_set_on_broker_side_close(self):
        prev = {"id": "888", "symbol": "XAUUSD", "entry_price": 4300.0, "sl_price": 4310.0, "sl": 4310.0, "tp_price": 4280.0, "tp": 4280.0, "current_price": 4310.0}
        self.seed_trade("T8", "888", direction="SELL", entry=4300.0, sl=4310.0, tp=4280.0, prev_position=prev)
        before = time.time()
        self.sync(self.snapshot())
        after = time.time()
        self.assertGreaterEqual(gateway.LAST_TRADE_CLOSE_TIMESTAMP, before)
        self.assertLessEqual(gateway.LAST_TRADE_CLOSE_TIMESTAMP, after)

    def test_timestamp_not_set_when_no_trades_closed(self):
        prev = {"id": "999", "symbol": "XAUUSD", "entry_price": 4300.0, "sl_price": 4290.0, "sl": 4290.0, "tp_price": 4310.0, "tp": 4310.0, "current_price": 4305.0}
        self.seed_trade("T9", "999", direction="BUY", entry=4300.0, sl=4290.0, tp=4310.0, prev_position=prev)
        gateway.LAST_TRADE_CLOSE_TIMESTAMP = 0.0
        self.sync(self.snapshot(positions=[{"id": 999, "symbol": "XAUUSD", "entry_price": 4300.0}]))
        self.assertEqual(gateway.LAST_TRADE_CLOSE_TIMESTAMP, 0.0)

    def test_cooldown_timestamp_set_on_broker_close(self):
        prev = {"id": "1010", "symbol": "XAUUSD", "entry_price": 4300.0, "sl_price": 4310.0, "sl": 4310.0, "tp_price": 4280.0, "tp": 4280.0, "current_price": 4310.0}
        self.seed_trade("T10", "1010", direction="SELL", entry=4300.0, sl=4310.0, tp=4280.0, prev_position=prev)
        gateway.LAST_TRADE_CLOSE_TIMESTAMP = 0.0
        self.sync(self.snapshot())
        self.assertGreater(gateway.LAST_TRADE_CLOSE_TIMESTAMP, 0)


class TestDuplicateRowPrevention(BrokerCloseFixture):
    def test_sync_cbot_closed_trade_updates_existing_trd_row(self):
        with self.connection() as conn:
            conn.execute(
                f"INSERT INTO trades ({TRADE_COLS}) VALUES (?, '', 'DEMO', '', '20001', 'XAUUSD', 'SELL', 4300, 4310, 4280, 0.01, 0.0, 0.0, 0.0, 0.0, 'OPEN', NULL, '2026-01-01', NULL)",
                ("TRD_TEST1",),
            )
            conn.commit()
        db.sync_cbot_closed_trade({
            "position_id": "20001",
            "trade_type": "SELL",
            "symbol": "XAUUSD",
            "entry_price": 4300.0,
            "closing_price": 4310.0,
            "net_profit": -10.0,
            "closing_time": "2026-09-14T16:00:00Z",
        })
        with self.connection() as conn:
            rows = conn.execute("SELECT id, status, exit_price FROM trades WHERE ticket_id='20001' OR id='TRD_TEST1'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(dict(rows[0])["status"], "CLOSED")
        self.assertEqual(dict(rows[0])["exit_price"], 4310.0)

    def test_sync_cbot_closed_trade_with_ct_prefix_finds_existing_trd(self):
        with self.connection() as conn:
            conn.execute(
                f"INSERT INTO trades ({TRADE_COLS}) VALUES (?, '', 'DEMO', '', 'CT_20002', 'XAUUSD', 'SELL', 4300, 4310, 4280, 0.01, 0.0, 0.0, 0.0, 0.0, 'OPEN', NULL, '2026-01-01', NULL)",
                ("TRD_TEST2",),
            )
            conn.commit()
        db.sync_cbot_closed_trade({
            "position_id": "CT_20002",
            "trade_type": "SELL",
            "symbol": "XAUUSD",
            "entry_price": 4300.0,
            "closing_price": 4308.0,
            "net_profit": -8.0,
            "closing_time": "2026-09-14T16:00:00Z",
            "entry_time": "2026-09-14T15:50:00Z",
        })
        with self.connection() as conn:
            ct_rows = conn.execute("SELECT id FROM trades WHERE id='CT_20002'").fetchall()
            self.assertEqual(len(ct_rows), 0)
            trd_rows = conn.execute("SELECT status, exit_price FROM trades WHERE id='TRD_TEST2'").fetchall()
            self.assertEqual(dict(trd_rows[0])["status"], "CLOSED")

    def test_no_duplicate_rows_when_trd_exists_with_bare_ticket(self):
        with self.connection() as conn:
            conn.execute(
                f"INSERT INTO trades ({TRADE_COLS}) VALUES (?, '', 'DEMO', '', '30003', 'XAUUSD', 'SELL', 4300, 4310, 4280, 0.01, 0.0, 0.0, 0.0, 0.0, 'OPEN', NULL, '2026-01-01', NULL)",
                ("TRD_TEST3",),
            )
            conn.commit()
        db.sync_cbot_closed_trade({
            "position_id": "30003",
            "trade_type": "SELL",
            "symbol": "XAUUSD",
            "entry_price": 4300.0,
            "closing_price": 4305.0,
            "net_profit": -5.0,
        })
        with self.connection() as conn:
            total = conn.execute("SELECT COUNT(*) as cnt FROM trades WHERE ticket_id='30003'").fetchone()["cnt"]
            self.assertEqual(total, 1)


class TestBrokerClosedHistoryIngestion(BrokerCloseFixture):
    """Tests for broker-authoritative closed-history path (restart recovery, idempotency, etc.)."""

    def _ingest_with_history(self, trade_items, positions=None):
        data = self.snapshot(positions=positions or [])
        data["history"] = trade_items
        self.sync(data)

    def test_restart_recovery_empty_prev_positions(self):
        self.seed_trade("T_REST1", "50001", direction="SELL", entry=4300.0, sl=4310.0, tp=4280.0)
        self._ingest_with_history([{
            "position_id": 50001,
            "symbol": "XAUUSD",
            "trade_type": "SELL",
            "volume": 0.01,
            "entry_price": 4300.0,
            "closing_price": 4309.5,
            "net_profit": -9.5,
            "closing_time": "2026-09-14T17:33:02Z",
            "entry_time": "2026-09-14T16:32:00Z",
        }])
        with self.connection() as conn:
            row = dict(conn.execute("SELECT * FROM trades WHERE id='T_REST1'").fetchone())
        self.assertEqual(row["status"], "CLOSED")
        self.assertEqual(row["exit_price"], 4309.5)
        self.assertAlmostEqual(row["profit_loss"], -9.5, places=2)
        self.assertEqual(row["is_broker_verified"], 1)

    def test_empty_prev_positions_by_id_still_persists_broker_financials(self):
        self.seed_trade("T_EMPTY", "50002", direction="BUY", entry=4300.0, sl=4290.0, tp=4315.0)
        self._ingest_with_history([{
            "position_id": 50002,
            "symbol": "XAUUSD",
            "trade_type": "BUY",
            "volume": 0.01,
            "entry_price": 4300.0,
            "closing_price": 4315.2,
            "net_profit": 15.2,
            "closing_time": "2026-09-14T17:40:00Z",
        }])
        with self.connection() as conn:
            row = dict(conn.execute("SELECT * FROM trades WHERE id='T_EMPTY'").fetchone())
        self.assertEqual(row["exit_price"], 4315.2)
        self.assertAlmostEqual(row["profit_loss"], 15.2, places=2)

    def test_broker_sl_close_history_ingestion(self):
        self.seed_trade("T_SL", "50003", direction="SELL", entry=4300.0, sl=4310.0, tp=4280.0)
        self._ingest_with_history([{
            "position_id": 50003,
            "symbol": "XAUUSD",
            "trade_type": "SELL",
            "volume": 0.01,
            "entry_price": 4300.0,
            "closing_price": 4310.0,
            "net_profit": -10.0,
            "closing_time": "2026-09-14T17:35:00Z",
            "close_reason": "Stop Loss Hit",
        }])
        with self.connection() as conn:
            row = dict(conn.execute("SELECT * FROM trades WHERE id='T_SL'").fetchone())
        self.assertEqual(row["exit_price"], 4310.0)
        self.assertAlmostEqual(row["profit_loss"], -10.0, places=2)
        self.assertIn("Stop Loss", row["close_reason"])

    def test_broker_tp_close_history_ingestion(self):
        self.seed_trade("T_TP", "50004", direction="BUY", entry=4300.0, sl=4290.0, tp=4310.0)
        self._ingest_with_history([{
            "position_id": 50004,
            "symbol": "XAUUSD",
            "trade_type": "BUY",
            "volume": 0.01,
            "entry_price": 4300.0,
            "closing_price": 4310.0,
            "net_profit": 10.0,
            "closing_time": "2026-09-14T17:45:00Z",
            "close_reason": "Take Profit Hit",
        }])
        with self.connection() as conn:
            row = dict(conn.execute("SELECT * FROM trades WHERE id='T_TP'").fetchone())
        self.assertEqual(row["exit_price"], 4310.0)
        self.assertAlmostEqual(row["profit_loss"], 10.0, places=2)
        self.assertIn("Take Profit", row["close_reason"])

    def test_exact_exit_price_from_broker_history(self):
        self.seed_trade("T_EP", "50005", direction="SELL", entry=4302.88, sl=4308.8, tp=4290.8)
        self._ingest_with_history([{
            "position_id": 50005,
            "symbol": "XAUUSD",
            "trade_type": "SELL",
            "volume": 0.01,
            "entry_price": 4302.88,
            "closing_price": 4310.36,
            "net_profit": -7.48,
            "pips": -74.8,
            "closing_time": "2026-09-14T17:33:02.611298+00:00",
        }])
        with self.connection() as conn:
            row = dict(conn.execute("SELECT * FROM trades WHERE id='T_EP'").fetchone())
        self.assertEqual(row["exit_price"], 4310.36)
        self.assertAlmostEqual(row["profit_loss"], -7.48, places=2)
        self.assertAlmostEqual(row["pips"], -74.8, places=1)

    def test_commission_and_swap_from_broker_history(self):
        self.seed_trade("T_CS", "50006", direction="BUY", entry=4300.0, sl=4290.0, tp=4315.0)
        self._ingest_with_history([{
            "position_id": 50006,
            "symbol": "XAUUSD",
            "trade_type": "BUY",
            "volume": 0.01,
            "entry_price": 4300.0,
            "closing_price": 4310.0,
            "net_profit": 10.0,
            "commission": -0.72,
            "swap": -0.35,
            "closing_time": "2026-09-14T18:00:00Z",
        }])
        with self.connection() as conn:
            row = dict(conn.execute("SELECT * FROM trades WHERE id='T_CS'").fetchone())
        self.assertEqual(row["commission"], -0.72)
        self.assertEqual(row["swap"], -0.35)

    def test_canonical_row_matching_by_ticket_id(self):
        with self.connection() as conn:
            conn.execute(
                f"INSERT INTO trades ({TRADE_COLS}) VALUES (?, '', 'DEMO', 'cTrader Cloud Fill (#60001)', '60001', 'XAUUSD', 'SELL', 4300, 4310, 4280, 0.01, 0.0, 0.0, 0.0, 0.0, 'OPEN', NULL, '2026-09-14', NULL)",
                ("TRD_CANON1",),
            )
            conn.commit()
        db.sync_cbot_closed_trade({
            "position_id": 60001,
            "trade_type": "SELL",
            "closing_price": 4308.0,
            "net_profit": -8.0,
            "closing_time": "2026-09-14T17:30:00Z",
        }, account_id="5908018")
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM trades WHERE ticket_id='60001' OR id='TRD_CANON1'").fetchall()
        self.assertEqual(len(rows), 1)
        row = dict(rows[0])
        self.assertEqual(row["id"], "TRD_CANON1")
        self.assertEqual(row["exit_price"], 4308.0)
        self.assertEqual(row["broker_account_id"], "5908018")

    def test_idempotent_repeated_reconciliation(self):
        self.seed_trade("T_IDEM", "70001", direction="SELL", entry=4300.0, sl=4310.0, tp=4280.0)
        history_item = {
            "position_id": 70001,
            "symbol": "XAUUSD",
            "trade_type": "SELL",
            "volume": 0.01,
            "entry_price": 4300.0,
            "closing_price": 4309.0,
            "net_profit": -9.0,
            "closing_time": "2026-09-14T17:33:02Z",
        }
        db.sync_cbot_closed_trade(dict(history_item), account_id="5908018")
        db.sync_cbot_closed_trade(dict(history_item), account_id="5908018")
        db.sync_cbot_closed_trade(dict(history_item), account_id="5908018")
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM trades WHERE id='T_IDEM'").fetchall()
        self.assertEqual(len(rows), 1)
        row = dict(rows[0])
        self.assertEqual(row["exit_price"], 4309.0)
        self.assertEqual(row["profit_loss"], -9.0)

    def test_no_duplicate_row_from_history_sync(self):
        with self.connection() as conn:
            conn.execute(
                f"INSERT INTO trades ({TRADE_COLS}) VALUES (?, '', 'DEMO', '', '80001', 'XAUUSD', 'SELL', 4300, 4310, 4280, 0.01, 0.0, 0.0, 0.0, 0.0, 'OPEN', NULL, '2026-01-01', NULL)",
                ("TRD_DUP1",),
            )
            conn.commit()
        for _ in range(5):
            db.sync_cbot_closed_trade({
                "position_id": 80001,
                "trade_type": "SELL",
                "closing_price": 4305.0,
                "net_profit": -5.0,
            }, account_id="5908018")
        with self.connection() as conn:
            total = conn.execute("SELECT COUNT(*) as cnt FROM trades WHERE ticket_id='80001'").fetchone()["cnt"]
            self.assertEqual(total, 1)

    def test_account_isolation_history_sync(self):
        with self.connection() as conn:
            conn.execute(
                f"INSERT INTO trades ({TRADE_COLS}) VALUES (?, '', 'DEMO', '', '90001', 'XAUUSD', 'SELL', 4300, 4310, 4280, 0.01, 0.0, 0.0, 0.0, 0.0, 'OPEN', NULL, '2026-01-01', NULL)",
                ("TRD_ACCT1",),
            )
            conn.commit()
        db.sync_cbot_closed_trade({
            "position_id": 90001,
            "trade_type": "SELL",
            "closing_price": 4306.0,
            "net_profit": -6.0,
        }, account_id="5908018")
        with self.connection() as conn:
            row = dict(conn.execute("SELECT broker_account_id FROM trades WHERE id='TRD_ACCT1'").fetchone())
        self.assertEqual(row["broker_account_id"], "5908018")

    def test_unavailable_broker_financials_not_fabricated(self):
        self.seed_trade("T_UNAVAIL", "95001", direction="BUY", entry=4300.0, sl=4290.0, tp=4315.0)
        self._ingest_with_history([{
            "position_id": 95001,
            "symbol": "XAUUSD",
            "trade_type": "BUY",
            "volume": 0.01,
            "entry_price": 4300.0,
            "closing_price": 0.0,
            "net_profit": 0.0,
            "closing_time": "2026-09-14T18:00:00Z",
        }])
        with self.connection() as conn:
            row = dict(conn.execute("SELECT * FROM trades WHERE id='T_UNAVAIL'").fetchone())
        self.assertEqual(row["status"], "CLOSED")
        self.assertIsNone(row["exit_price"])
        self.assertEqual(row["profit_loss"], 0.0)


class TestExecutionIntentDirection(BrokerCloseFixture):
    def test_execution_intent_records_actual_sell_action(self):
        db.record_execution_intent(
            intent_id="INTENT_SELL_001",
            signal_id="SIG_SELL_001",
            action="SELL",
            status="DISPATCHING",
            provenance="BROKER_DEMO",
        )
        intent = db.get_execution_intent("INTENT_SELL_001")
        self.assertIsNotNone(intent)
        self.assertEqual(intent["action"], "SELL")

    def test_execution_intent_records_buy_action(self):
        db.record_execution_intent(
            intent_id="INTENT_BUY_001",
            signal_id="SIG_BUY_001",
            action="BUY",
            status="DISPATCHING",
            provenance="BROKER_DEMO",
        )
        intent = db.get_execution_intent("INTENT_BUY_001")
        self.assertIsNotNone(intent)
        self.assertEqual(intent["action"], "BUY")

    def test_execution_intent_defaults_to_buy_when_no_action(self):
        db.record_execution_intent(
            intent_id="INTENT_DEFAULT_001",
            signal_id="SIG_DEFAULT_001",
            status="DISPATCHING",
            provenance="BROKER_DEMO",
        )
        intent = db.get_execution_intent("INTENT_DEFAULT_001")
        self.assertEqual(intent["action"], "BUY")


if __name__ == "__main__":
    unittest.main()

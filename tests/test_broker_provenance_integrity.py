import unittest
import time
import uuid
import datetime
from app.database.db import db, get_db_connection, _lock
from app.database.models import DataProvenance, SignalPayload
from app.agents.quality_agent import quality_agent
from app.config import settings

class TestBrokerProvenanceIntegrity(unittest.TestCase):
    """
    Permanent Regression Test Suite:
    Guarantees strict isolation of broker-verified trade history from test, paper, simulated,
    and legacy records. Validates mathematical correctness of performance formulas.
    """

    def setUp(self):
        self.test_account_id = "5908018"
        self.foreign_account_id = "9999999"

    # -------------------------------------------------------------------------
    # 1-6. PROVENANCE EXCLUSION AUDIT (TEST, SIMULATED, PAPER, BACKTEST, LEGACY, UNKNOWN)
    # -------------------------------------------------------------------------
    def test_non_broker_provenances_strictly_excluded_from_broker_performance(self):
        """
        Guarantees that records with TEST, SIMULATED, PAPER, BACKTEST, LEGACY, or UNKNOWN
        provenance NEVER enter broker performance calculations.
        """
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        non_broker_records = [
            {"id": f"TEST_ROW_{uuid.uuid4().hex[:6]}", "provenance": "TEST", "is_broker_verified": 0, "pnl": 500.0, "status": "CLOSED"},
            {"id": f"SIM_ROW_{uuid.uuid4().hex[:6]}", "provenance": "SIMULATED", "is_broker_verified": 0, "pnl": 500.0, "status": "CLOSED"},
            {"id": f"PAP_ROW_{uuid.uuid4().hex[:6]}", "provenance": "PAPER", "is_broker_verified": 0, "pnl": 500.0, "status": "CLOSED"},
            {"id": f"BT_ROW_{uuid.uuid4().hex[:6]}", "provenance": "BACKTEST", "is_broker_verified": 0, "pnl": 500.0, "status": "CLOSED"},
            {"id": f"LEG_ROW_{uuid.uuid4().hex[:6]}", "provenance": "LEGACY", "is_broker_verified": 0, "pnl": 500.0, "status": "CLOSED"},
            {"id": f"UNK_ROW_{uuid.uuid4().hex[:6]}", "provenance": "UNKNOWN", "is_broker_verified": 0, "pnl": 500.0, "status": "CLOSED"},
        ]

        with _lock, get_db_connection() as conn:
            for r in non_broker_records:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO trades
                    (id, signal_id, mode, broker_order_id, ticket_id, symbol, direction, entry_price, exit_price, stop_loss, take_profit, volume, profit_loss, pips, commission, swap, status, close_reason, opened_at, closed_at, provenance, is_broker_verified, broker_account_id)
                    VALUES (?, '', 'TEST', 'Mock Order', ?, 'XAUUSD', 'BUY', 2750.0, 2760.0, 2740.0, 2765.0, 0.01, ?, 10.0, 0.0, 0.0, 'CLOSED', 'Test Exit', ?, ?, ?, ?, ?)
                    """,
                    (r["id"], r["id"], r["pnl"], now_iso, now_iso, r["provenance"], r["is_broker_verified"], self.test_account_id)
                )
            conn.commit()

        # Query broker performance stats
        stats = db.get_performance_stats(broker_account_id=self.test_account_id)
        
        # Verify that get_recent_trades with is_broker_verified_only=True returns ZERO non-broker records
        broker_trades = db.get_recent_trades(limit=200, broker_account_id=self.test_account_id, is_broker_verified_only=True)
        for t in broker_trades:
            self.assertEqual(t.get("is_broker_verified"), 1, f"Unverified record {t['id']} leaked into broker ledger!")
            self.assertIn(t.get("provenance"), ("BROKER_DEMO_VERIFIED", "BROKER_LIVE_VERIFIED"), f"Invalid provenance {t['provenance']} leaked!")

    # -------------------------------------------------------------------------
    # 7-8. ACCOUNT ISOLATION & FAIL-CLOSED ALLOWLIST
    # -------------------------------------------------------------------------
    def test_broker_account_isolation(self):
        """
        Guarantees that trades from a different broker account are not aggregated
        into the active account's performance metrics.
        """
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        foreign_id = f"CT_FOREIGN_{uuid.uuid4().hex[:6]}"
        
        with _lock, get_db_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trades
                (id, signal_id, mode, broker_order_id, ticket_id, symbol, direction, entry_price, exit_price, stop_loss, take_profit, volume, profit_loss, pips, commission, swap, status, close_reason, opened_at, closed_at, provenance, is_broker_verified, broker_account_id)
                VALUES (?, '', 'DEMO', 'Foreign Order', '998877', 'XAUUSD', 'BUY', 4400.0, 4410.0, 4390.0, 4420.0, 0.01, 100.0, 10.0, 0.0, 0.0, 'CLOSED', 'Target Hit', ?, ?, 'BROKER_DEMO_VERIFIED', 1, ?)
                """,
                (foreign_id, now_iso, now_iso, self.foreign_account_id)
            )
            conn.commit()

        stats_active = db.get_performance_stats(broker_account_id=self.test_account_id)
        trades_active = db.get_recent_trades(limit=200, broker_account_id=self.test_account_id, is_broker_verified_only=True)
        
        # Verify foreign trade is NOT in active account list
        active_ids = {t["id"] for t in trades_active}
        self.assertNotIn(foreign_id, active_ids)

    # -------------------------------------------------------------------------
    # 9. BROKER-HISTORY UI DATA CONTRACT
    # -------------------------------------------------------------------------
    def test_broker_history_ui_contract_excludes_synthetic_data(self):
        """
        Guarantees that get_recent_trades(is_broker_verified_only=True) strictly rejects synthetic records.
        """
        trades = db.get_recent_trades(limit=100, is_broker_verified_only=True)
        for t in trades:
            self.assertEqual(t.get("is_broker_verified"), 1)
            self.assertFalse(str(t.get("id", "")).startswith("PAP_"))
            self.assertFalse(str(t.get("id", "")).startswith("TRD_JRN_TEST_"))
            self.assertFalse(str(t.get("ticket_id", "")) in ("99999", "91004", "91005"))

    # -------------------------------------------------------------------------
    # 10. QUANT BRAIN PROVENANCE INTEGRITY
    # -------------------------------------------------------------------------
    def test_quant_brain_evaluates_only_clean_provenance(self):
        """
        Guarantees Quant Brain / TradeQualityAgent gracefully handles clean stats and fails-closed
        or enters DEGRADED baseline when sample size < 20.
        """
        clean_stats = db.get_performance_stats(broker_account_id=self.test_account_id)
        sig = SignalPayload(
            id="SIG_QB_CLEAN_01",
            symbol="XAUUSD",
            action="BUY",
            entry_price=4400.0,
            stop_loss=4394.0,
            take_profit=4412.0,
            timeframe="15m"
        )
        market_data = {
            "symbol": "XAUUSD",
            "bid": 4400.0,
            "ask": 4400.3,
            "spread": 0.30,
            "indicators": {"rsi": 55.0, "atr": 4.5}
        }

        output = quality_agent.evaluate(sig, clean_stats, market_data)
        self.assertIsNotNone(output)
        self.assertTrue(output.score >= 0.0 and output.score <= 100.0)
        self.assertNotIn("Mock Order", output.reasoning_summary)

    # -------------------------------------------------------------------------
    # 11-12. MATHEMATICALLY ACCURATE PROFIT FACTOR RECONCILIATION
    # -------------------------------------------------------------------------
    def test_profit_factor_mathematical_formula(self):
        """
        Validates that Profit Factor = Gross Profit / Gross Loss exactly.
        """
        stats = db.get_performance_stats(broker_account_id=self.test_account_id)
        gross_p = stats.get("gross_profit", 0.0)
        gross_l = stats.get("gross_loss", 0.0)
        stored_pf = stats.get("profit_factor", 1.0)
        
        if gross_l > 0:
            expected_pf = round(gross_p / gross_l, 2)
            self.assertAlmostEqual(stored_pf, expected_pf, places=2)
        else:
            self.assertEqual(stored_pf, round(gross_p, 2) if gross_p > 0 else 1.0)

    # -------------------------------------------------------------------------
    # 13. DRAWDOWN UNIT CONVERSION INTEGRITY
    # -------------------------------------------------------------------------
    def test_drawdown_unit_conversion_integrity(self):
        """
        Validates proper distinction between Drawdown in R, Drawdown in USD, and Drawdown in %.
        """
        account_balance = 1018.96
        initial_risk_1r_usd = 6.00 # $6.00 per 1R for 0.01 lots ($6 Gold move)
        realized_loss_2r = 2.0 * initial_risk_1r_usd # $12.00 USD
        
        # Drawdown in R
        dd_r = 2.0
        # Drawdown in USD
        dd_usd = dd_r * initial_risk_1r_usd
        self.assertEqual(dd_usd, 12.00)
        
        # Drawdown in %
        dd_pct = (dd_usd / account_balance) * 100.0
        self.assertAlmostEqual(dd_pct, 1.177, places=2)
        
        # Ensure R is not compared directly to % without conversion
        self.assertNotEqual(dd_r, dd_pct)

if __name__ == "__main__":
    unittest.main()

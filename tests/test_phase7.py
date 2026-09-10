import unittest
import time
import datetime
from fastapi.testclient import TestClient
from main_native import app
from app.services.paper_trading_engine import paper_trading_engine, PaperPosition
from app.services.journal_analytics import journal_analytics_service
from app.services.performance_analytics import performance_engine
from app.database.db import db, get_db_connection

client = TestClient(app)

class TestPhase7PaperJournalPerformance(unittest.TestCase):
    def setUp(self):
        # Reset virtual paper account
        paper_trading_engine.reset_account(initial_balance=1000.0)

    def test_01_paper_order_execution_and_margin(self):
        """Tests simulated paper order placement, volume clamping, and margin deduction."""
        res = paper_trading_engine.place_order(
            symbol="XAUUSD",
            direction="BUY",
            volume=0.01,
            current_bid=2750.00,
            current_ask=2750.35,
            stop_loss=2744.00,
            take_profit=2762.00,
            strategy_name="Gold_Sniper_Phase7",
            market_regime="TRENDING"
        )
        self.assertEqual(res["status"], "EXECUTED_PAPER")
        pos = res["position"]
        self.assertEqual(pos["symbol"], "XAUUSD")
        self.assertEqual(pos["direction"], "BUY")
        self.assertEqual(pos["volume"], 0.01)
        self.assertEqual(pos["entry_price"], 2750.35)
        self.assertGreater(pos["margin_required"], 0.0)
        
        # Verify account margin tracking
        summary = paper_trading_engine.get_account_summary()
        self.assertEqual(summary["open_positions_count"], 1)
        self.assertAlmostEqual(summary["balance"], 1000.0, places=2)
        self.assertLess(summary["free_margin"], 1000.0)

    def test_02_tick_processing_and_mfe_mae_tracking(self):
        """Tests tick updates calculating unrealized PnL and tracking peak MFE / worst MAE."""
        res = paper_trading_engine.place_order(
            symbol="XAUUSD",
            direction="BUY",
            volume=0.01,
            current_bid=2750.00,
            current_ask=2750.30,
            stop_loss=2740.00,
            take_profit=2770.00
        )
        pos_id = res["position"]["position_id"]
        
        # Tick 1: Price goes up (Favorable excursion)
        # Entry at 2750.30. Bid moves to 2755.30 -> +5.00 points = +500 pips
        paper_trading_engine.on_tick("XAUUSD", bid=2755.30, ask=2755.60)
        pos = paper_trading_engine.open_positions[pos_id]
        self.assertGreater(pos.peak_mfe_pips, 0.0)
        self.assertGreater(pos.unrealized_pnl, 0.0)
        
        # Tick 2: Price dips below entry (Adverse excursion)
        paper_trading_engine.on_tick("XAUUSD", bid=2748.30, ask=2748.60)
        self.assertLess(pos.worst_mae_pips, 0.0)
        self.assertLess(pos.unrealized_pnl, 0.0)
        # Peak MFE should still preserve the highest point reached
        self.assertGreaterEqual(pos.peak_mfe_pips, 500.0)

    def test_03_take_profit_and_stop_loss_hit_detection(self):
        """Tests automatic SL/TP hit detection during live tick streaming."""
        # Test TP Trigger
        tp_res = paper_trading_engine.place_order(
            symbol="XAUUSD",
            direction="BUY",
            volume=0.01,
            current_bid=2750.00,
            current_ask=2750.30,
            stop_loss=2740.00,
            take_profit=2760.00
        )
        tp_pos_id = tp_res["position"]["position_id"]
        
        # Price spikes to 2761.00 (above TP 2760.00)
        closed_events = paper_trading_engine.on_tick("XAUUSD", bid=2761.00, ask=2761.35, high=2761.50)
        self.assertEqual(len(closed_events), 1)
        self.assertEqual(closed_events[0]["position"]["close_reason"], "TAKE_PROFIT_HIT")
        self.assertNotIn(tp_pos_id, paper_trading_engine.open_positions)
        self.assertGreater(paper_trading_engine.balance, 1000.0)

        # Test SL Trigger
        sl_res = paper_trading_engine.place_order(
            symbol="XAUUSD",
            direction="BUY",
            volume=0.01,
            current_bid=2750.00,
            current_ask=2750.30,
            stop_loss=2745.00,
            take_profit=2765.00
        )
        sl_pos_id = sl_res["position"]["position_id"]
        
        # Price drops to 2744.00 (below SL 2745.00)
        closed_events_sl = paper_trading_engine.on_tick("XAUUSD", bid=2744.00, ask=2744.30, low=2744.00)
        self.assertEqual(len(closed_events_sl), 1)
        self.assertEqual(closed_events_sl[0]["position"]["close_reason"], "STOP_LOSS_HIT")
        self.assertNotIn(sl_pos_id, paper_trading_engine.open_positions)

    def test_04_trade_journal_logging_and_note_update(self):
        """Tests automatic post-trade journaling, MFE/MAE recording, and note editing."""
        # Seed a closed trade in journal
        trade_id = f"TRD_JRN_TEST_{int(time.time())}"
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        db.save_trade({
            "id": trade_id,
            "mode": "PAPER",
            "symbol": "XAUUSD",
            "direction": "BUY",
            "entry_price": 2750.00,
            "exit_price": 2758.00,
            "stop_loss": 2744.00,
            "take_profit": 2762.00,
            "volume": 0.01,
            "profit_loss": 8.00,
            "pips": 800.0,
            "status": "CLOSED",
            "close_reason": "TAKE_PROFIT_HIT",
            "opened_at": now_iso,
            "closed_at": now_iso
        })

        journal_entry = {
            "id": f"JRN_{trade_id}",
            "trade_id": trade_id,
            "symbol": "XAUUSD",
            "direction": "BUY",
            "strategy_name": "Gold_Sniper_SMC",
            "market_regime": "TRENDING_BULLISH",
            "mfe": 950.0,
            "mae": -120.0,
            "trade_duration_seconds": 1200,
            "ai_reasoning": "5-Agent Quorum buy approved.",
            "notes": "Initial trade entry."
        }
        db.save_trade_journal_entry(journal_entry)

        # Query journal entries via service
        entries = journal_analytics_service.get_journal_entries(symbol="XAUUSD", outcome="WIN")
        self.assertGreater(len(entries), 0)
        found = next((e for e in entries if e["trade_id"] == trade_id), None)
        self.assertIsNotNone(found)
        self.assertEqual(found["mfe"], 950.0)
        self.assertEqual(found["mae"], -120.0)
        self.assertTrue(found["is_win"])

        # Update note
        updated = journal_analytics_service.update_journal_notes(f"JRN_{trade_id}", "Updated: Flawless execution with trailing stop.")
        self.assertTrue(updated)
        details = journal_analytics_service.get_entry_details(f"JRN_{trade_id}")
        self.assertEqual(details["notes"], "Updated: Flawless execution with trailing stop.")

    def test_05_quantitative_performance_analytics(self):
        """Tests institutional metrics: Sharpe, Sortino, Drawdown %, Expectancy, and Win Rate."""
        metrics = performance_engine.calculate_full_performance()
        self.assertIn("win_rate", metrics)
        self.assertIn("profit_factor", metrics)
        self.assertIn("expectancy", metrics)
        self.assertIn("sharpe_ratio", metrics)
        self.assertIn("max_drawdown_dollars", metrics)
        self.assertIn("max_drawdown_pct", metrics)

        # Equity Curve Test
        curve = performance_engine.generate_equity_curve(initial_balance=1000.0)
        self.assertIsInstance(curve, list)
        self.assertGreaterEqual(len(curve), 1)
        self.assertEqual(curve[0]["trade_num"], 0)
        self.assertEqual(curve[0]["balance"], 1000.0)

        # Breakdown Test
        breakdown = performance_engine.get_breakdown_analytics()
        self.assertIn("by_symbol", breakdown)
        self.assertIn("by_direction", breakdown)
        self.assertIn("by_regime", breakdown)
        self.assertIn("by_weekday", breakdown)

    def test_06_fastapi_rest_endpoints(self):
        """Tests all Phase 7 Paper, Journal, and Performance REST API routes."""
        # 1. Paper Order API
        order_payload = {
            "symbol": "XAUUSD",
            "direction": "SELL",
            "volume": 0.01,
            "current_bid": 2750.00,
            "current_ask": 2750.35,
            "stop_loss": 2756.00,
            "take_profit": 2738.00,
            "strategy_name": "API_Test_Order",
            "market_regime": "TRENDING"
        }
        res = client.post("/api/paper/order", json=order_payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "EXECUTED_PAPER")
        pos_id = data["position"]["position_id"]

        # 2. Paper Account & Positions API
        acc_res = client.get("/api/paper/account")
        self.assertEqual(acc_res.status_code, 200)
        self.assertEqual(acc_res.json()["account_type"], "PAPER")

        pos_res = client.get("/api/paper/positions")
        self.assertEqual(pos_res.status_code, 200)
        self.assertGreaterEqual(len(pos_res.json()["open_positions"]), 1)

        # 3. Close Paper Position API
        close_res = client.post(f"/api/paper/close/{pos_id}", json={"reason": "API_CLOSE"})
        self.assertEqual(close_res.status_code, 200)
        self.assertEqual(close_res.json()["status"], "SUCCESS")

        # 4. Journal Entries & Notes API
        j_res = client.get("/api/journal/entries?limit=10")
        self.assertEqual(j_res.status_code, 200)
        self.assertIsInstance(j_res.json(), list)

        note_res = client.put(f"/api/journal/entry/JRN_{pos_id}/notes", json={"notes": "FastAPI client verified note."})
        self.assertEqual(note_res.status_code, 200)

        # 5. MFE/MAE Matrix API
        matrix_res = client.get("/api/journal/mfe-mae-matrix")
        self.assertEqual(matrix_res.status_code, 200)
        self.assertIn("matrix_points", matrix_res.json())

        # 6. Performance Overview & Equity Curve API
        perf_res = client.get("/api/performance/overview")
        self.assertEqual(perf_res.status_code, 200)
        self.assertIn("win_rate", perf_res.json())

        eq_res = client.get("/api/performance/equity-curve")
        self.assertEqual(eq_res.status_code, 200)
        self.assertIsInstance(eq_res.json(), list)

        bd_res = client.get("/api/performance/breakdown")
        self.assertEqual(bd_res.status_code, 200)
        self.assertIn("by_symbol", bd_res.json())

if __name__ == "__main__":
    unittest.main()

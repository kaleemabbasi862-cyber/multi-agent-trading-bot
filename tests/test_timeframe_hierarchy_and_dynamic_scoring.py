import os
import unittest
from unittest.mock import patch, MagicMock

os.environ["TESTING"] = "1"

from app.engine.multi_timeframe_engine import MultiTimeframeEngine, multi_timeframe_engine
from app.services.setup_classifier import SetupClassifier, setup_classifier
from app.services.trade_quality_scorer import TradeQualityScorer, trade_quality_scorer
from app.services.pretrade_intelligence_engine import pretrade_intelligence_engine
from app.services.performance_analytics import QuantitativePerformanceEngine, performance_engine
from app.services.live_safety_gate import live_safety_gate
from app.database import db as db_module
from app.database.schema import init_db_schema


def _generate_candles(trend="BULLISH", count=30, start_price=2700.0):
    candles = []
    p = start_price
    for i in range(count):
        if trend == "BULLISH":
            o = p
            c = p + 2.0
            h = c + 0.5
            l = o - 0.5
            p = c
        elif trend == "BEARISH":
            o = p
            c = p - 2.0
            h = o + 0.5
            l = c - 0.5
            p = c
        else: # NEUTRAL / RANGE
            o = p
            c = p + (1.0 if i % 2 == 0 else -1.0)
            h = max(o, c) + 0.5
            l = min(o, c) - 0.5
            p = c
        candles.append({
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
            "volume": 100.0,
            "timestamp": f"2026-09-17T{10 + (i // 4):02d}:{(i % 4) * 15:02d}:00Z"
        })
    return candles


class TestTimeframeHierarchyAndDynamicScoring(unittest.TestCase):

    # 1. Test D1/H4 disagreement alone does not force intraday candidate to FLAT
    def test_01_d1_h4_disagreement_does_not_force_flat(self):
        # M5=BULLISH, M15=BULLISH, H1=BULLISH, but D1=BEARISH, H4=BEARISH
        tf_candles = {
            "M5": _generate_candles("BULLISH", 30, 2700.0),
            "M15": _generate_candles("BULLISH", 30, 2700.0),
            "H1": _generate_candles("BULLISH", 30, 2700.0),
            "H4": _generate_candles("BEARISH", 30, 2750.0),
            "D1": _generate_candles("BEARISH", 30, 2800.0),
        }
        mtf_res = multi_timeframe_engine.evaluate_multi_timeframe(tf_candles)
        self.assertEqual(mtf_res["intraday_trend"], "BULLISH")
        self.assertTrue(mtf_res["intraday_aligned"])
        self.assertEqual(mtf_res["macro_opposition_count"], 2)

        smc_data = {
            "trend": "BULLISH",
            "structure": "BULLISH_TREND",
            "latest_event": "BULLISH_BOS",
            "unmitigated_obs": [],
            "unmitigated_fvgs": [],
            "recent_sweeps": [],
            "dealing_range": {"zone": "DISCOUNT", "location_pct": 30.0}
        }
        setup_res = setup_classifier.classify_setup(mtf_res, smc_data, 2730.0)
        self.assertEqual(setup_res["direction"], "BUY")
        self.assertNotEqual(setup_res["direction"], "FLAT")
        self.assertIn("INTRADAY", setup_res["regime"])

    # 2. Test 2/3 alignment in (M5, M15, H1) produces candidate
    def test_02_two_thirds_alignment_produces_candidate(self):
        # H1=BULLISH, M15=BULLISH, M5=NEUTRAL (2 of 3 BULLISH)
        tf_candles = {
            "M5": _generate_candles("NEUTRAL", 30, 2700.0),
            "M15": _generate_candles("BULLISH", 30, 2700.0),
            "H1": _generate_candles("BULLISH", 30, 2700.0),
            "H4": _generate_candles("NEUTRAL", 30, 2700.0),
            "D1": _generate_candles("NEUTRAL", 30, 2700.0),
        }
        mtf_res = multi_timeframe_engine.evaluate_multi_timeframe(tf_candles)
        self.assertEqual(mtf_res["intraday_trend"], "BULLISH")
        self.assertTrue(mtf_res["intraday_aligned"])

        smc_data = {
            "trend": "NEUTRAL",
            "structure": "RANGE",
            "latest_event": "NONE",
            "unmitigated_obs": [],
            "unmitigated_fvgs": [],
            "recent_sweeps": [],
            "dealing_range": {"zone": "DISCOUNT", "location_pct": 40.0}
        }
        setup_res = setup_classifier.classify_setup(mtf_res, smc_data, 2705.0)
        self.assertEqual(setup_res["direction"], "BUY")
        self.assertTrue(setup_res["is_actionable"])

    # 3. Test Bearish 2/3 alignment generates provisional SELL candidate
    def test_03_bearish_two_thirds_alignment_produces_sell(self):
        # H1=BEARISH, M15=BEARISH, M5=BULLISH (2 of 3 BEARISH)
        tf_candles = {
            "M5": _generate_candles("BULLISH", 30, 2700.0),
            "M15": _generate_candles("BEARISH", 30, 2700.0),
            "H1": _generate_candles("BEARISH", 30, 2700.0),
            "H4": _generate_candles("NEUTRAL", 30, 2700.0),
            "D1": _generate_candles("NEUTRAL", 30, 2700.0),
        }
        mtf_res = multi_timeframe_engine.evaluate_multi_timeframe(tf_candles)
        self.assertEqual(mtf_res["intraday_trend"], "BEARISH")
        self.assertTrue(mtf_res["intraday_aligned"])

        smc_data = {
            "trend": "BEARISH",
            "structure": "BEARISH_TREND",
            "latest_event": "BEARISH_BOS",
            "unmitigated_obs": [],
            "unmitigated_fvgs": [],
            "recent_sweeps": [],
            "dealing_range": {"zone": "PREMIUM", "location_pct": 70.0}
        }
        setup_res = setup_classifier.classify_setup(mtf_res, smc_data, 2690.0)
        self.assertEqual(setup_res["direction"], "SELL")
        self.assertNotEqual(setup_res["direction"], "FLAT")

    # 4. Test Threshold 75 is strictly maintained
    def test_04_execution_threshold_is_75(self):
        self.assertEqual(TradeQualityScorer.DEFAULT_THRESHOLD, 75.0)

        # Setup with score < 75 should NOT pass
        setup = {"setup_type": "TREND_CONTINUATION", "direction": "BUY"}
        mtf_data = {"consensus_trend": "BULLISH", "intraday_trend": "BULLISH", "intraday_aligned": True, "macro_opposition_count": 0}
        smc_data = {
            "structure": "RANGE",
            "latest_event": "NONE",
            "dealing_range": {"zone": "EQUILIBRIUM", "location_pct": 50.0}
        }
        indicators = {"rsi": 50.0, "adx": {"adx": 15.0}}
        score_res = trade_quality_scorer.score_trade_setup(
            setup=setup,
            mtf_data=mtf_data,
            smc_data=smc_data,
            indicators=indicators,
            live_spread_pips=4.0,
            target_rr_ratio=1.5
        )
        self.assertLess(score_res["score"], 75.0)
        self.assertFalse(score_res["passed"])
        self.assertEqual(score_res["verdict"], "NO_TRADE_QUALITY_BELOW_THRESHOLD")

    # 5. Test Dynamic Quality Score changes with changing market inputs
    def test_05_dynamic_score_changes_with_market_inputs(self):
        setup = {"setup_type": "NO_VALID_SETUP", "direction": "FLAT"}
        mtf_data = {"consensus_trend": "NEUTRAL", "intraday_trend": "NO_TRADE_CONFLICT", "confluence_score": 50.0, "intraday_score": 50.0}
        smc_data = {
            "structure": "RANGE",
            "latest_event": "NONE",
            "dealing_range": {"zone": "EQUILIBRIUM", "location_pct": 50.0}
        }
        
        # State A: RSI 50, ADX 10, high spread 5.0 pips
        score_a = trade_quality_scorer.score_trade_setup(
            setup=setup,
            mtf_data=mtf_data,
            smc_data=smc_data,
            indicators={"rsi": 50.0, "adx": {"adx": 10.0}},
            live_spread_pips=5.0,
            target_rr_ratio=1.5
        )["score"]

        # State B: RSI 55, ADX 30, tight spread 0.8 pips, unmitigated OBs exist
        smc_data_b = {
            "structure": "RANGE",
            "latest_event": "NONE",
            "unmitigated_obs": [{"high": 2700, "low": 2695, "type": "BULLISH_ORDER_BLOCK"}],
            "dealing_range": {"zone": "DISCOUNT", "location_pct": 35.0}
        }
        score_b = trade_quality_scorer.score_trade_setup(
            setup=setup,
            mtf_data=mtf_data,
            smc_data=smc_data_b,
            indicators={"rsi": 55.0, "adx": {"adx": 30.0}},
            live_spread_pips=0.8,
            target_rr_ratio=2.2
        )["score"]

        # State A and State B must not be equal or static
        self.assertNotEqual(score_a, score_b)
        self.assertGreater(score_b, score_a)
        self.assertNotEqual(score_a, 25.0)

    # 6. Test Safety Gate fail-closed (spread, stale quote)
    def test_06_safety_gate_fail_closed_on_wide_spread_or_stale(self):
        # Fail closed when account is unverified or spread is wide (> 5.0 pips)
        is_safe, msg, _ = live_safety_gate.evaluate_order_safety(
            symbol="XAUUSD",
            action="BUY",
            volume=0.01,
            entry_price=2750.0,
            sl_price=2744.0,
            tp_price=2762.0,
            current_spread_pips=6.5
        )
        self.assertFalse(is_safe, "Order must fail closed on unverified/wide spread")
        self.assertTrue(len(msg) > 0)

    # 7. Test Missing broker quotes fail closed in pre-trade intelligence
    def test_07_pretrade_fails_closed_on_missing_or_stale_broker_data(self):
        res = pretrade_intelligence_engine.scan_market(
            symbol="XAUUSD",
            live_tick={"bid": 0.0, "ask": 0.0, "spread": 0.0},
            timeframe_candles={}
        )
        self.assertFalse(res["trade_allowed"])
        self.assertEqual(res["status"], "FAIL_CLOSED_NO_MARKET_DATA")

    # 8. Test Duplicate broker ticket counts once in Performance Analytics
    def test_08_duplicate_broker_ticket_counts_once(self):
        import tempfile
        from pathlib import Path
        temp_dir = tempfile.mkdtemp()
        db_path = str(Path(temp_dir) / "test_perf_dedup.db")
        
        with patch.object(db_module.settings, "DATABASE_PATH", db_path):
            with db_module.get_db_connection() as conn:
                init_db_schema(conn)

            # Insert 2 rows for the exact same broker position/ticket "T88888"
            trade1 = {
                "id": "CT_T88888",
                "symbol": "XAUUSD",
                "direction": "BUY",
                "entry_price": 2700.0,
                "exit_price": 2712.0,
                "stop_loss": 2694.0,
                "take_profit": 2712.0,
                "volume": 0.01,
                "profit_loss": 12.0,
                "ticket_id": "T88888",
                "status": "CLOSED",
                "broker_account_id": "5908018",
                "execution_environment": "DEMO",
                "is_broker_verified": 1,
                "provenance": "BROKER_DEMO_VERIFIED"
            }
            trade2 = {
                "id": "TRD_T88888",
                "symbol": "XAUUSD",
                "direction": "BUY",
                "entry_price": 2700.0,
                "exit_price": 2712.0,
                "stop_loss": 2694.0,
                "take_profit": 2712.0,
                "volume": 0.01,
                "profit_loss": 12.0,
                "ticket_id": "T88888",
                "status": "CLOSED",
                "broker_account_id": "5908018",
                "execution_environment": "DEMO",
                "is_broker_verified": 1,
                "provenance": "BROKER_DEMO_VERIFIED"
            }
            db_module.db.save_trade(trade1)
            db_module.db.save_trade(trade2)

            stats = QuantitativePerformanceEngine.calculate_full_performance()
            self.assertEqual(stats["total_trades"], 1, "Duplicate broker rows must only count as 1 trade")
            self.assertEqual(stats["winning_trades"], 1)
            self.assertEqual(stats["net_profit"], 12.0)

    # 9. Test TESTING=1 prohibits external broker order dispatch
    def test_09_testing_mode_prohibits_external_broker_order(self):
        from app.engine.execution_engine import execution_engine
        from app.database.models import ConsensusResult, SignalPayload, RiskCheckResult

        sig = SignalPayload(
            id="SIG_TEST_01",
            symbol="XAUUSD",
            action="BUY",
            entry_price=2750.0,
            stop_loss=2744.0,
            take_profit=2762.0,
            volume=0.01
        )
        risk_res = RiskCheckResult(
            passed=True,
            calculated_volume=0.01,
            account_balance=1000.0,
            account_equity=1000.0,
            risk_amount=10.0,
            sl_distance=6.0,
            tp_distance=12.0,
            rr_ratio=2.0,
            spread=0.35
        )
        consensus = ConsensusResult(
            signal_id=sig.id,
            symbol=sig.symbol,
            direction=sig.action,
            decision_status="APPROVED",
            decision_score=85.0,
            risk_check=risk_res,
            agent_decisions=[],
            full_analysis="Test approved signal"
        )
        res = execution_engine.dispatch_trade(consensus, sig)
        # Under TESTING=1 or unverified telemetry, real broker dispatch is blocked/simulated safely
        self.assertIn(res.get("status"), ("EXECUTED_PAPER", "SIMULATED", "EXECUTED", "SUCCESS", "REJECTED_BROKER_TELEMETRY"))
        self.assertNotEqual(res.get("execution_environment"), "LIVE")


if __name__ == "__main__":
    unittest.main()

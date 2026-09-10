import unittest
from fastapi.testclient import TestClient
from main_native import app
from app.services.historical_data_service import historical_data_service
from app.services.backtesting_engine import backtesting_engine
from app.services.walk_forward_engine import walk_forward_engine
from app.services.monte_carlo_engine import monte_carlo_engine

class TestPhase8BacktestingAndValidation(unittest.TestCase):
    """
    Test suite for Phase 8: Strategy Backtesting, Walk-Forward Validation & Monte Carlo Engine.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_01_historical_data_service(self):
        """Test multi-regime candle synthesis and caching."""
        candles = historical_data_service.get_candles(symbol="XAUUSD", timeframe="15m", days=10)
        self.assertGreater(len(candles), 100)
        first_candle = candles[0]
        self.assertIn("open", first_candle)
        self.assertIn("high", first_candle)
        self.assertIn("low", first_candle)
        self.assertIn("close", first_candle)
        self.assertIn("volume", first_candle)
        self.assertIn("timestamp", first_candle)
        self.assertGreaterEqual(first_candle["high"], first_candle["low"])

    def test_02_backtesting_engine_execution(self):
        """Test backtest execution across institutional strategies."""
        strategies = ["Gold_Sniper_SMC_v2", "Trend_Confluence_15m_1h", "London_NY_Breakout", "Mean_Reversion_BB_RSI"]
        for strat in strategies:
            res = backtesting_engine.run_backtest(
                strategy_name=strat,
                symbol="XAUUSD",
                timeframe="15m",
                days_back=20,
                initial_balance=1000.0,
                spread_pips=0.35,
                slippage_pips=0.10,
                volume=0.01
            )
            self.assertEqual(res["status"], "COMPLETED")
            self.assertEqual(res["strategy_name"], strat)
            self.assertIn("win_rate", res)
            self.assertIn("profit_factor", res)
            self.assertIn("net_profit", res)
            self.assertIn("max_drawdown_pct", res)
            self.assertIn("trades", res)
            self.assertIsInstance(res["trades"], list)

    def test_03_walk_forward_validation_engine(self):
        """Test 4-fold In-Sample vs Out-of-Sample Walk-Forward Efficiency (WFE %) computation."""
        wf_res = walk_forward_engine.run_walk_forward_validation(
            strategy_name="Gold_Sniper_SMC_v2",
            symbol="XAUUSD",
            timeframe="15m",
            total_days=40,
            num_folds=4,
            is_ratio=0.70,
            initial_balance=1000.0
        )
        self.assertEqual(wf_res["status"], "COMPLETED")
        self.assertIn("average_wfe_pct", wf_res)
        self.assertIn("verdict", wf_res)
        self.assertEqual(len(wf_res["folds"]), 4)
        for fold in wf_res["folds"]:
            self.assertIn("in_sample", fold)
            self.assertIn("out_of_sample", fold)
            self.assertIn("walk_forward_efficiency", fold)
            self.assertGreater(fold["in_sample"]["candles_count"], 0)
            self.assertGreater(fold["out_of_sample"]["candles_count"], 0)

    def test_04_monte_carlo_resampling_simulation(self):
        """Test 1,000-iteration bootstrap Monte Carlo simulation & risk percentiles."""
        mc_res = monte_carlo_engine.run_simulation(
            strategy_name="Gold_Sniper_SMC_v2",
            symbol="XAUUSD",
            initial_capital=1000.0,
            num_simulations=500,
            trades_per_simulation=50,
            ruin_drawdown_threshold_pct=20.0
        )
        self.assertEqual(mc_res["status"], "COMPLETED")
        self.assertEqual(mc_res["num_simulations"], 500)
        self.assertIn("prob_of_ruin_pct", mc_res)
        self.assertIn("drawdown_confidence_intervals", mc_res)
        self.assertIn("percentiles", mc_res)
        self.assertIn("p50_median_equity", mc_res["percentiles"])
        self.assertIn("p5_worst_case_equity", mc_res["percentiles"])
        self.assertIn("p95_best_case_equity", mc_res["percentiles"])

    def test_05_backtest_rest_api_endpoints(self):
        """Test FastAPI endpoints for Strategy Lab catalog, backtest, walk-forward, monte-carlo, and history."""
        # 1. Strategies catalog
        res_cat = self.client.get("/api/backtest/strategies")
        self.assertEqual(res_cat.status_code, 200)
        data_cat = res_cat.json()
        self.assertIn("strategies", data_cat)
        self.assertGreaterEqual(len(data_cat["strategies"]), 4)

        # 2. Run backtest
        payload_bt = {
            "strategy_name": "Gold_Sniper_SMC_v2",
            "symbol": "XAUUSD",
            "timeframe": "15m",
            "days_back": 15,
            "initial_balance": 1000.0,
            "spread_pips": 0.35,
            "slippage_pips": 0.10,
            "volume": 0.01
        }
        res_bt = self.client.post("/api/backtest/run", json=payload_bt)
        self.assertEqual(res_bt.status_code, 200)
        data_bt = res_bt.json()
        self.assertEqual(data_bt["status"], "COMPLETED")

        # 3. Walk-Forward API
        payload_wf = {
            "strategy_name": "Gold_Sniper_SMC_v2",
            "symbol": "XAUUSD",
            "timeframe": "15m",
            "total_days": 30,
            "num_folds": 3,
            "is_ratio": 0.70,
            "initial_balance": 1000.0
        }
        res_wf = self.client.post("/api/backtest/walk-forward", json=payload_wf)
        self.assertEqual(res_wf.status_code, 200)
        data_wf = res_wf.json()
        self.assertEqual(data_wf["status"], "COMPLETED")
        self.assertEqual(len(data_wf["folds"]), 3)

        # 4. Monte Carlo API
        payload_mc = {
            "strategy_name": "Gold_Sniper_SMC_v2",
            "symbol": "XAUUSD",
            "initial_capital": 1000.0,
            "num_simulations": 200,
            "trades_per_simulation": 40,
            "ruin_drawdown_threshold_pct": 20.0
        }
        res_mc = self.client.post("/api/backtest/monte-carlo", json=payload_mc)
        self.assertEqual(res_mc.status_code, 200)
        data_mc = res_mc.json()
        self.assertEqual(data_mc["status"], "COMPLETED")

        # 5. History API
        res_hist = self.client.get("/api/backtest/history?limit=10")
        self.assertEqual(res_hist.status_code, 200)
        data_hist = res_hist.json()
        self.assertIsInstance(data_hist, list)

if __name__ == "__main__":
    unittest.main()

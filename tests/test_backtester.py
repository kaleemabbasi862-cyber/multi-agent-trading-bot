from app.database.models import BacktestRequest
from app.engine.backtester import backtester

def test_strategy_lab_backtest_execution():
    req = BacktestRequest(
        strategy_name="Gold_Sniper_SMC_v2",
        symbol="XAUUSD",
        timeframe="15m",
        days_back=15,
        initial_balance=1000.0,
        spread_pips=3.5,
        slippage_pips=1.0
    )
    res = backtester.run_backtest(req)
    assert res["id"].startswith("BT_")
    assert res["total_trades"] >= 0
    assert "win_rate" in res
    assert "profit_factor" in res
    assert "expectancy" in res
    assert "equity_curve" in res

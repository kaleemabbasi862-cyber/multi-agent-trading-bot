from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import json
from app.services.backtesting_engine import backtesting_engine
from app.services.walk_forward_engine import walk_forward_engine
from app.services.monte_carlo_engine import monte_carlo_engine
from app.database.db import get_db_connection

router = APIRouter(prefix="/api/backtest", tags=["Strategy Lab & Backtesting"])

class BacktestRunRequest(BaseModel):
    strategy_name: str = Field("Gold_Sniper_SMC_v2", example="Gold_Sniper_SMC_v2")
    symbol: str = Field("XAUUSD", example="XAUUSD")
    timeframe: str = Field("15m", example="15m")
    days_back: int = Field(30, ge=5, le=180, example=30)
    initial_balance: float = Field(1000.0, ge=10.0, example=1000.0)
    spread_pips: float = Field(0.35, ge=0.0, example=0.35)
    slippage_pips: float = Field(0.10, ge=0.0, example=0.10)
    volume: float = Field(0.01, ge=0.01, le=10.0, example=0.01)

class WalkForwardRequest(BaseModel):
    strategy_name: str = Field("Gold_Sniper_SMC_v2", example="Gold_Sniper_SMC_v2")
    symbol: str = Field("XAUUSD", example="XAUUSD")
    timeframe: str = Field("15m", example="15m")
    total_days: int = Field(60, ge=20, le=180, example=60)
    num_folds: int = Field(4, ge=2, le=10, example=4)
    is_ratio: float = Field(0.70, ge=0.50, le=0.85, example=0.70)
    initial_balance: float = Field(1000.0, example=1000.0)

class MonteCarloRequest(BaseModel):
    strategy_name: str = Field("Gold_Sniper_SMC_v2", example="Gold_Sniper_SMC_v2")
    symbol: str = Field("XAUUSD", example="XAUUSD")
    initial_capital: float = Field(1000.0, example=1000.0)
    num_simulations: int = Field(1000, ge=100, le=5000, example=1000)
    trades_per_simulation: int = Field(100, ge=20, le=500, example=100)
    ruin_drawdown_threshold_pct: float = Field(20.0, ge=5.0, le=90.0, example=20.0)

@router.get("/strategies")
async def get_strategies_catalog():
    """Returns catalog of quantitative backtesting strategies with parameter metadata."""
    return {
        "strategies": backtesting_engine.AVAILABLE_STRATEGIES
    }

@router.post("/run")
async def run_backtest_strategy(req: BacktestRunRequest):
    """Runs high-fidelity event-driven strategy backtest with spread, slippage, and intrabar fills."""
    return backtesting_engine.run_backtest(
        strategy_name=req.strategy_name,
        symbol=req.symbol,
        timeframe=req.timeframe,
        days_back=req.days_back,
        initial_balance=req.initial_balance,
        spread_pips=req.spread_pips,
        slippage_pips=req.slippage_pips,
        volume=req.volume
    )

@router.post("/walk-forward")
async def run_walk_forward_validation(req: WalkForwardRequest):
    """Executes multi-fold In-Sample vs Out-of-Sample Walk-Forward validation to compute WFE %."""
    return walk_forward_engine.run_walk_forward_validation(
        strategy_name=req.strategy_name,
        symbol=req.symbol,
        timeframe=req.timeframe,
        total_days=req.total_days,
        num_folds=req.num_folds,
        is_ratio=req.is_ratio,
        initial_balance=req.initial_balance
    )

@router.post("/monte-carlo")
async def run_monte_carlo_simulation(req: MonteCarloRequest):
    """Runs 1,000+ iteration bootstrap Monte Carlo resampling for probability of ruin and drawdown bounds."""
    return monte_carlo_engine.run_simulation(
        strategy_name=req.strategy_name,
        symbol=req.symbol,
        initial_capital=req.initial_capital,
        num_simulations=req.num_simulations,
        trades_per_simulation=req.trades_per_simulation,
        ruin_drawdown_threshold_pct=req.ruin_drawdown_threshold_pct
    )

@router.get("/history")
async def get_backtest_history(limit: int = Query(20, ge=1, le=100)):
    """Returns stored historical strategy backtests from SQLite database."""
    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM strategy_backtests ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        results = []
        for r in rows:
            item = dict(r)
            if item.get("metrics_json"):
                try:
                    item["metrics"] = json.loads(item["metrics_json"])
                except Exception:
                    pass
            results.append(item)
        return results

@router.get("/{backtest_id}")
async def get_backtest_by_id(backtest_id: str):
    """Retrieves full details of a specific saved backtest run."""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM strategy_backtests WHERE id = ?", (backtest_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Backtest #{backtest_id} not found.")
        item = dict(row)
        if item.get("metrics_json"):
            try:
                item["metrics"] = json.loads(item["metrics_json"])
            except Exception:
                pass
        return item

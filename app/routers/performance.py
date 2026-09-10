from fastapi import APIRouter, Query
from typing import Optional, Dict, Any, List
from app.services.performance_analytics import performance_engine

router = APIRouter(prefix="/api/performance", tags=["Performance Analytics"])

@router.get("/overview")
async def get_performance_overview(mode: Optional[str] = Query(None, description="PAPER, DEMO, LIVE or ALL")):
    """Returns complete quantitative metrics summary including Sharpe, Sortino, Drawdown, Expectancy, and Win Rate."""
    return performance_engine.calculate_full_performance(trades_filter_mode=mode)

@router.get("/equity-curve")
async def get_equity_curve(initial_balance: float = Query(1000.0, ge=10.0)):
    """Returns time-series balance and equity curve with per-trade drawdown."""
    return performance_engine.generate_equity_curve(initial_balance=initial_balance)

@router.get("/breakdown")
async def get_performance_breakdown():
    """Returns multidimensional performance breakdowns by Symbol, Direction, Market Regime, and Weekday."""
    return performance_engine.get_breakdown_analytics()

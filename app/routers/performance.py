from fastapi import APIRouter, Query
from typing import Optional, Dict, Any, List
from app.services.performance_analytics import performance_engine
import settings_manager

router = APIRouter(prefix="/api/performance", tags=["Performance Analytics"])

@router.get("/overview")
async def get_performance_overview(
    mode: Optional[str] = Query(None, description="PAPER, DEMO, LIVE or ALL"),
    account_id: Optional[str] = Query(None, description="Broker account ID")
):
    """Returns complete quantitative metrics summary including Sharpe, Sortino, Drawdown, Expectancy, and Win Rate."""
    active_mode = mode or settings_manager.load_settings().get("trading_mode", "DEMO")
    active_acc = account_id or settings_manager.get_active_account_id() or "5908018"
    return performance_engine.calculate_full_performance(
        trades_filter_mode=active_mode,
        broker_account_id=active_acc,
        is_broker_verified_only=True
    )

@router.get("/equity-curve")
async def get_equity_curve(
    initial_balance: float = Query(1000.0, ge=10.0),
    mode: Optional[str] = Query(None, description="PAPER, DEMO, LIVE or ALL"),
    account_id: Optional[str] = Query(None, description="Broker account ID")
):
    """Returns time-series balance and equity curve with per-trade drawdown."""
    active_mode = mode or settings_manager.load_settings().get("trading_mode", "DEMO")
    active_acc = account_id or settings_manager.get_active_account_id() or "5908018"
    return performance_engine.generate_equity_curve(
        initial_balance=initial_balance,
        trades_filter_mode=active_mode,
        broker_account_id=active_acc,
        is_broker_verified_only=True
    )

@router.get("/breakdown")
async def get_performance_breakdown(
    mode: Optional[str] = Query(None, description="PAPER, DEMO, LIVE or ALL"),
    account_id: Optional[str] = Query(None, description="Broker account ID")
):
    """Returns multidimensional performance breakdowns by Symbol, Direction, Market Regime, and Weekday."""
    active_mode = mode or settings_manager.load_settings().get("trading_mode", "DEMO")
    active_acc = account_id or settings_manager.get_active_account_id() or "5908018"
    return performance_engine.get_breakdown_analytics(
        trades_filter_mode=active_mode,
        broker_account_id=active_acc,
        is_broker_verified_only=True
    )

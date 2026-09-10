from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from app.services.ctrader_execution_service import ctrader_execution_service
from app.services.live_safety_gate import live_safety_gate
from app.services.autonomous_trader import autonomous_trader

router = APIRouter(prefix="/api/execution", tags=["cTrader Execution & Autonomous Engine"])

class MarketOrderRequest(BaseModel):
    symbol: str = Field("XAUUSD", example="XAUUSD")
    action: str = Field("BUY", example="BUY")
    volume: float = Field(0.01, ge=0.01, le=10.0, example=0.01)
    sl_price: Optional[float] = Field(None, example=2744.00)
    tp_price: Optional[float] = Field(None, example=2762.00)
    comment: Optional[str] = Field("Manual Order via TradeTalk Desktop", example="Manual Order via TradeTalk Desktop")
    signal_id: Optional[str] = Field(None, example="SIG_TEST_001")
    ignore_news_lockout: bool = Field(False, example=False)

class ClosePositionRequest(BaseModel):
    position_id: Any = Field(..., example="99999")
    force: bool = Field(False, example=False)

class PartialCloseRequest(BaseModel):
    position_id: Any = Field(..., example="99999")
    close_volume: float = Field(0.01, ge=0.01, le=10.0, example=0.01)

class ModifySLTPRequest(BaseModel):
    position_id: Any = Field(..., example="99999")
    sl_price: Optional[float] = Field(None, example=2748.00)
    tp_price: Optional[float] = Field(None, example=2765.00)

class BreakEvenRequest(BaseModel):
    position_id: Any = Field(..., example="99999")
    buffer_pips: float = Field(1.0, ge=0.0, le=10.0, example=1.0)

class AutonomousSetupRequest(BaseModel):
    symbol: str = Field("XAUUSD", example="XAUUSD")
    action: str = Field("BUY", example="BUY")
    entry_price: float = Field(2750.00, example=2750.00)
    stop_loss: float = Field(2744.00, example=2744.00)
    take_profit: float = Field(2762.00, example=2762.00)
    timeframe: str = Field("15m", example="15m")
    force_execute: bool = Field(False, example=False)

@router.post("/order")
async def execute_market_order_endpoint(req: MarketOrderRequest):
    """Executes market order on cTrader Open API."""
    return ctrader_execution_service.execute_market_order(
        symbol=req.symbol,
        action=req.action,
        volume=req.volume,
        sl_price=req.sl_price,
        tp_price=req.tp_price,
        comment=req.comment or "TradeTalk Order",
        signal_id=req.signal_id,
        ignore_news_lockout=req.ignore_news_lockout
    )

@router.post("/close")
async def close_position_endpoint(req: ClosePositionRequest):
    """Closes an open cTrader position."""
    return ctrader_execution_service.close_position(
        position_id=req.position_id,
        force=req.force
    )

@router.post("/partial-close")
async def partial_close_endpoint(req: PartialCloseRequest):
    """Partially closes an open position (e.g. at 1.5R target)."""
    return ctrader_execution_service.partial_close_position(
        position_id=req.position_id,
        close_volume=req.close_volume
    )

@router.post("/modify-sltp")
async def modify_sltp_endpoint(req: ModifySLTPRequest):
    """Modifies SL/TP levels on an active cTrader position."""
    return ctrader_execution_service.modify_position_sltp(
        position_id=req.position_id,
        new_sl=req.sl_price,
        new_tp=req.tp_price
    )

@router.post("/break-even")
async def break_even_endpoint(req: BreakEvenRequest):
    """Moves Stop Loss to entry price + buffer pips for a risk-free trade."""
    return ctrader_execution_service.move_to_break_even(
        position_id=req.position_id,
        buffer_pips=req.buffer_pips
    )

@router.get("/positions")
async def get_open_positions_endpoint():
    """Returns all active open positions tracked in gateway."""
    return {
        "open_positions": ctrader_execution_service.get_open_positions(),
        "summary": ctrader_execution_service.get_account_summary()
    }

@router.post("/safety-check")
async def run_safety_check_endpoint(
    symbol: str = Query("XAUUSD"),
    action: str = Query("BUY"),
    volume: float = Query(0.01),
    entry_price: float = Query(2750.0),
    sl_price: float = Query(2744.0),
    tp_price: float = Query(2762.0),
    ignore_news_lockout: bool = Query(False)
):
    """Evaluates proposed setup against all 6 safety gates."""
    is_safe, reason, telemetry = live_safety_gate.evaluate_order_safety(
        symbol=symbol,
        action=action,
        volume=volume,
        entry_price=entry_price,
        sl_price=sl_price,
        tp_price=tp_price,
        ignore_news_lockout=ignore_news_lockout
    )
    return {
        "is_approved": is_safe,
        "reason": reason,
        "telemetry": telemetry
    }

@router.post("/autonomous/process-setup")
async def process_autonomous_setup_endpoint(req: AutonomousSetupRequest):
    """Full-pipeline autonomous trade evaluation, consensus scoring, safety gating & execution."""
    return autonomous_trader.process_market_setup(
        symbol=req.symbol,
        action=req.action,
        entry_price=req.entry_price,
        stop_loss=req.stop_loss,
        take_profit=req.take_profit,
        timeframe=req.timeframe,
        force_execute=req.force_execute
    )

@router.post("/autonomous/toggle")
async def toggle_autonomous_mode():
    """Starts or stops the autonomous trading pipeline."""
    is_now_running = autonomous_trader.toggle()
    return {
        "is_running": is_now_running,
        "message": "Autonomous Multi-Agent Trading Activated" if is_now_running else "Autonomous Trading Paused"
    }

@router.get("/autonomous/status")
async def get_autonomous_status():
    """Returns autonomous trader operational status and parameters."""
    return autonomous_trader.get_status()

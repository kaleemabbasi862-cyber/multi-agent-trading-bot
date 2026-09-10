from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from app.services.paper_trading_engine import paper_trading_engine

router = APIRouter(prefix="/api/paper", tags=["Paper Trading Engine"])

class PaperOrderRequest(BaseModel):
    symbol: str = Field(..., example="XAUUSD")
    direction: str = Field(..., example="BUY") # 'BUY' or 'SELL'
    volume: float = Field(0.01, example=0.01)
    current_bid: float = Field(..., example=2750.00)
    current_ask: float = Field(..., example=2750.35)
    stop_loss: float = Field(..., example=2744.00)
    take_profit: float = Field(..., example=2762.00)
    signal_id: Optional[str] = None
    strategy_name: Optional[str] = "Autonomous_7Agent"
    market_regime: Optional[str] = "TRENDING"
    slippage_pips: Optional[float] = 0.0

class PaperCloseRequest(BaseModel):
    exit_price: Optional[float] = None
    reason: Optional[str] = "MANUAL_CLOSE"

class PaperModifyRequest(BaseModel):
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

class PaperDepositRequest(BaseModel):
    amount: float = Field(..., example=1000.0)

@router.post("/order")
async def place_paper_order(req: PaperOrderRequest):
    """Executes a simulated paper order with authentic spread and margin checks."""
    res = paper_trading_engine.place_order(
        symbol=req.symbol,
        direction=req.direction,
        volume=req.volume,
        current_bid=req.current_bid,
        current_ask=req.current_ask,
        stop_loss=req.stop_loss,
        take_profit=req.take_profit,
        signal_id=req.signal_id,
        strategy_name=req.strategy_name or "Autonomous_7Agent",
        market_regime=req.market_regime or "TRENDING",
        slippage_pips=req.slippage_pips or 0.0
    )
    if res.get("status", "").startswith("REJECTED"):
        raise HTTPException(status_code=400, detail=res)
    return res

@router.post("/close/{position_id}")
async def close_paper_position(position_id: str, req: Optional[PaperCloseRequest] = None):
    """Closes an active paper position and journals the post-trade results."""
    exit_p = req.exit_price if req else None
    reason = req.reason if req and req.reason else "MANUAL_CLOSE"
    res = paper_trading_engine.close_position(position_id, exit_price=exit_p, reason=reason)
    if res.get("status") == "ERROR":
        raise HTTPException(status_code=404, detail=res.get("message"))
    return res

@router.post("/modify/{position_id}")
async def modify_paper_position(position_id: str, req: PaperModifyRequest):
    """Modifies Stop Loss and Take Profit levels on an open paper trade."""
    res = paper_trading_engine.modify_position(position_id, stop_loss=req.stop_loss, take_profit=req.take_profit)
    if res.get("status") == "ERROR":
        raise HTTPException(status_code=404, detail=res.get("message"))
    return res

@router.get("/positions")
async def get_paper_positions():
    """Returns all active open and historical closed paper trading positions."""
    return {
        "open_positions": [p.to_dict() for p in paper_trading_engine.open_positions.values()],
        "closed_positions": paper_trading_engine.closed_positions
    }

@router.get("/account")
async def get_paper_account():
    """Returns virtual balance, equity, margin, and margin level."""
    return paper_trading_engine.get_account_summary()

@router.post("/reset")
async def reset_paper_account(initial_balance: float = 1000.0):
    """Resets paper trading account to a clean initial deposit."""
    return paper_trading_engine.reset_account(initial_balance=initial_balance)

@router.post("/deposit")
async def deposit_paper_funds(req: PaperDepositRequest):
    """Deposits virtual funds into paper account."""
    return paper_trading_engine.deposit_funds(req.amount)

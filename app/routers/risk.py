import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.database.db import db
from app.services.risk_engine import risk_engine
import cbot_bridge

logger = logging.getLogger("TradeTalk.Router.Risk")
router = APIRouter(prefix="/api/risk", tags=["Risk Management"])


@router.get("/telemetry")
@router.get("/status")
async def get_risk_status():
    """Returns consolidated real-time risk telemetry, circuit breakers, and exposure."""
    try:
        acc_status = cbot_bridge.get_cbot_status()
        telemetry = risk_engine.get_risk_telemetry(acc_status)
        return {
            "status": "SUCCESS",
            "data": telemetry
        }
    except Exception as e:
        logger.error(f"Error fetching risk telemetry: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class PositionSizeRequest(BaseModel):
    symbol: str = "XAUUSD"
    account_equity: float = 1000.0
    entry_price: float = 2350.0
    stop_loss: float = 2345.0
    risk_percentage: Optional[float] = 1.0
    max_lot_cap: Optional[float] = None


@router.post("/calculate-size")
async def calculate_position_size(req: PositionSizeRequest):
    """
    Computes exact mathematical position size based on risk percentage, SL distance,
    and broker contract lot specifications.
    """
    try:
        result = risk_engine.calculate_position_size(
            symbol=req.symbol,
            account_equity=req.account_equity,
            entry_price=req.entry_price,
            stop_loss=req.stop_loss,
            risk_percentage=req.risk_percentage,
            max_lot_cap=req.max_lot_cap
        )
        return {
            "status": "SUCCESS",
            "data": result
        }
    except Exception as e:
        logger.error(f"Error calculating position size: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/circuit-breaker/reset")
async def reset_circuit_breaker():
    """Manually resets active circuit breakers and cooldown counters."""
    try:
        res = risk_engine.reset_circuit_breaker()
        return res
    except Exception as e:
        logger.error(f"Error resetting circuit breaker: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/events")
async def get_risk_events(limit: int = Query(default=50, ge=1, le=200)):
    """Fetches risk event audit logs from SQLite."""
    try:
        events = db.get_risk_events(limit=limit)
        return {
            "status": "SUCCESS",
            "count": len(events),
            "events": events
        }
    except Exception as e:
        logger.error(f"Error fetching risk events: {e}")
        raise HTTPException(status_code=500, detail=str(e))

import logging
from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from app.database.db import db
from app.services.economic_calendar import economic_calendar

logger = logging.getLogger("TradeTalk.Router.Calendar")
router = APIRouter(prefix="/api/calendar", tags=["Economic Calendar"])


@router.get("/events")
async def get_calendar_events(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    impact: Optional[str] = None,
    currency: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200)
):
    """Retrieves economic calendar events from SQLite with optional filtering."""
    try:
        events = db.get_economic_events(
            start_time=start_time,
            end_time=end_time,
            impact=impact,
            currency=currency,
            limit=limit
        )
        return {
            "status": "SUCCESS",
            "count": len(events),
            "events": events
        }
    except Exception as e:
        logger.error(f"Error fetching calendar events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/lockout-status")
async def get_lockout_status(
    symbol: str = Query(default="XAUUSD"),
    spread: Optional[float] = Query(default=None)
):
    """
    Evaluates real-time high-impact news protection lockout status,
    active blackout window, post-news cooldown, and spread normalization.
    """
    try:
        status = economic_calendar.check_lockout_status(symbol=symbol, current_spread=spread)
        return {
            "status": "SUCCESS",
            "data": status
        }
    except Exception as e:
        logger.error(f"Error checking lockout status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/macro-status")
async def get_macro_status(
    symbol: str = Query(default="XAUUSD"),
    spread: Optional[float] = Query(default=None)
):
    """Returns aggregated macro status dictionary for Guardian and Consensus modules."""
    try:
        macro = economic_calendar.get_macro_status(symbol=symbol, current_spread=spread)
        return {
            "status": "SUCCESS",
            "data": macro
        }
    except Exception as e:
        logger.error(f"Error getting macro status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class SyncCalendarRequest(BaseModel):
    mode: Optional[str] = "SCHEDULE_REFRESH"


@router.post("/sync")
async def sync_economic_calendar(req: Optional[SyncCalendarRequest] = None):
    """Triggers real live ForexFactory economic calendar feed sync and database refresh."""
    try:
        events = economic_calendar.sync_live_calendar(force=True)
        return {
            "status": "SUCCESS",
            "message": f"Successfully synced {len(events)} real live macroeconomic events.",
            "synced_count": len(events)
        }
    except Exception as e:
        logger.error(f"Error syncing economic calendar: {e}")
        raise HTTPException(status_code=500, detail=str(e))

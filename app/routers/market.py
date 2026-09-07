from fastapi import APIRouter
from app.services.market_feed_v2 import get_gold_market_snapshot
from app.services.economic_calendar import economic_calendar

router = APIRouter(prefix="/api", tags=["Market"])

@router.get("/market-prices")
@router.get("/live-prices")
async def get_live_prices():
    gold_data = get_gold_market_snapshot()
    return {"XAUUSD": gold_data}

@router.get("/market/macro")
async def get_macro_status():
    return economic_calendar.get_macro_status()

from fastapi import APIRouter
from app.services.market_feed_v2 import get_market_snapshot, get_gold_market_snapshot
from app.services.economic_calendar import economic_calendar
import settings_manager

router = APIRouter(prefix="/api", tags=["Market"])

@router.get("/market-prices")
@router.get("/live-prices")
async def get_live_prices():
    symbols = ["XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF"]
    prices = {}
    for s in symbols:
        prices[s] = get_market_snapshot(s)
    return prices

@router.get("/market/macro")
async def get_macro_status():
    return economic_calendar.get_macro_status()

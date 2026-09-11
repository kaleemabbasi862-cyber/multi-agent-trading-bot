from fastapi import APIRouter
from app.services.market_feed_v2 import get_market_snapshot, get_gold_market_snapshot
from app.services.economic_calendar import economic_calendar
import settings_manager
import ctrader_cloud_gateway as gateway
from app.services.broker_telemetry import health

router = APIRouter(prefix="/api", tags=["Market"])

@router.get("/market-prices")
@router.get("/live-prices")
async def get_live_prices():
    gateway.get_gateway_status()
    symbols = ["XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF"]
    prices = {}
    for s in symbols:
        quote = gateway.get_live_price(s)
        telemetry = health(gateway.GATEWAY_STATE, s)
        prices[s] = {"symbol": s, "price": None, "bid": None, "ask": None,
                     "source": "CTRADER_CBOT", "executable": False, "stale": True,
                     "telemetry": telemetry, **(quote or {})}
        prices[s]["executable"] = bool(quote)
        prices[s]["stale"] = not bool(quote)
    return prices

@router.get("/market/macro")
async def get_macro_status():
    return economic_calendar.get_macro_status()

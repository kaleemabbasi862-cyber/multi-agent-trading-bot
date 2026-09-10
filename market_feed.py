import time
import math
import traceback
from datetime import datetime
import pandas as pd
import numpy as np
import requests
import yfinance as yf
from app.services.market_feed_v2 import (
    get_market_snapshot,
    get_gold_market_snapshot,
    compute_live_candle_indicators,
    PAIR_METADATA
)
import cbot_bridge

# Whitelist
TICKER_MAP = {
    "XAUUSD": {"yf": "GC=F", "name": "Gold / US Dollar", "spread": 0.35, "decimals": 2, "pip_size": 0.01},
}

def calculate_multi_timeframe_indicators(closes_15m: pd.Series, closes_1h: pd.Series = None, decimals: int = 2):
    """Calculates Multi-Timeframe Alignment for XAUUSD (Gold)."""
    meta = PAIR_METADATA.get("XAUUSD", {"digits": decimals, "pip": 0.01, "yahoo": "GC=F"})
    return compute_live_candle_indicators("XAUUSD", meta).get("indicators", {})

def fetch_single_ticker(symbol: str, meta: dict = None):
    """Fetches real-time price & genuine candle indicators."""
    snapshot = get_market_snapshot(symbol, force_refresh=False)
    return snapshot

def get_realtime_market_feed(force_refresh: bool = False) -> dict:
    """Returns real-time prices for Gold (XAUUSD)."""
    data = get_market_snapshot("XAUUSD", force_refresh=force_refresh)
    return {"XAUUSD": data}

get_live_market_data = get_realtime_market_feed
get_live_prices = get_realtime_market_feed

def get_live_ticker(symbol: str = "XAUUSD") -> dict:
    """Helper to get XAUUSD Gold ticker data."""
    return get_market_snapshot(symbol, force_refresh=False)

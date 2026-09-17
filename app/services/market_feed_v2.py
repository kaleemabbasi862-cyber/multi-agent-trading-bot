import datetime
import time
from typing import Any, Dict, List

import pandas as pd

from app.config import settings
from app.services.broker_candle_feed import get_broker_multi_timeframe_candles
import cbot_bridge

_FEED_CACHE: Dict[str, Dict[str, Any]] = {}
_FEED_TIMESTAMPS: Dict[str, float] = {}

PAIR_METADATA = {
    "XAUUSD": {"name": "Gold / USD", "pip": 0.01, "digits": 2},
    "XAGUSD": {"name": "Silver / USD", "pip": 0.001, "digits": 3},
    "EURUSD": {"name": "EUR / USD", "pip": 0.0001, "digits": 5},
    "GBPUSD": {"name": "GBP / USD", "pip": 0.0001, "digits": 5},
    "USDJPY": {"name": "USD / JPY", "pip": 0.01, "digits": 3},
    "AUDUSD": {"name": "AUD / USD", "pip": 0.0001, "digits": 5},
    "USDCHF": {"name": "USD / CHF", "pip": 0.0001, "digits": 5},
}


def _clean_symbol(symbol: str) -> str:
    cleaned = symbol.upper().replace(".PRO", "").replace("_I", "")
    if cleaned not in PAIR_METADATA:
        raise RuntimeError(f"UNSUPPORTED_BROKER_SYMBOL:{cleaned}")
    return cleaned

def _ema(values: List[float], span: int) -> float:
    if not values:
        raise RuntimeError("BROKER_CANDLES_EMPTY")
    return float(pd.Series(values, dtype="float64").ewm(span=span, adjust=False).mean().iloc[-1])


def _rsi(values: List[float], period: int = 14) -> float:
    if len(values) < period + 1:
        raise RuntimeError("BROKER_CANDLES_INSUFFICIENT_FOR_RSI")
    series = pd.Series(values, dtype="float64")
    delta = series.diff()
    gain = delta.clip(lower=0.0).rolling(period, min_periods=period).mean()
    loss = (-delta.clip(upper=0.0)).rolling(period, min_periods=period).mean()
    latest_gain = float(gain.iloc[-1])
    latest_loss = float(loss.iloc[-1])
    if latest_loss == 0:
        return 100.0
    rs = latest_gain / latest_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _broker_indicators(candles: Dict[str, Any], digits: int) -> Dict[str, Any]:
    m15 = candles["M15"]
    h1 = candles["H1"]
    d1 = candles["D1"]
    closes_15 = [float(bar["close"]) for bar in m15]
    closes_1h = [float(bar["close"]) for bar in h1]
    last_24 = m15[-24:]
    price = closes_15[-1]
    ema20 = _ema(closes_15, 20)
    ema50 = _ema(closes_15, 50)
    ema200 = _ema(closes_15, 200)
    ema20_1h = _ema(closes_1h, 20)
    ema50_1h = _ema(closes_1h, 50)
    high_24h = max(float(bar["high"]) for bar in last_24)
    low_24h = min(float(bar["low"]) for bar in last_24)
    day_open = float(d1[-1]["open"])
    change_24h = ((price - day_open) / day_open * 100.0) if day_open else 0.0
    return {
        "change_24h": round(change_24h, 2),
        "high_24h": round(high_24h, digits),
        "low_24h": round(low_24h, digits),
        "indicators": {
            "rsi": round(_rsi(closes_15), 1),
            "ema_20": round(ema20, digits),
            "ema_50": round(ema50, digits),
            "ema_200": round(ema200, digits),
            "ema_20_1h": round(ema20_1h, digits),
            "ema_50_1h": round(ema50_1h, digits),
            "trend": "BULLISH" if price >= ema50 else "BEARISH",
            "trend_1h": "BULLISH" if ema20_1h >= ema50_1h else "BEARISH",
            "support": round(low_24h, digits),
            "resistance": round(high_24h, digits),
        },
    }


def get_market_snapshot(symbol: str = "XAUUSD", force_refresh: bool = False) -> Dict[str, Any]:
    """Return a broker-authoritative snapshot. No proxy or synthetic fallback is allowed."""
    global _FEED_CACHE, _FEED_TIMESTAMPS
    sym = _clean_symbol(symbol)
    meta = PAIR_METADATA[sym]
    now_ts = time.time()

    if not force_refresh and sym in _FEED_CACHE:
        age = now_ts - _FEED_TIMESTAMPS.get(sym, 0.0)
        if age < 2.0:
            return _FEED_CACHE[sym]

    quote = cbot_bridge.get_cbot_live_price(sym)
    if not isinstance(quote, dict):
        raise RuntimeError(f"BROKER_QUOTE_UNAVAILABLE:{sym}")
    quote_at = float(quote.get("updated_at") or quote.get("quote_at") or 0.0)
    if quote_at <= 0 or now_ts - quote_at > settings.MAX_MARKET_DATA_AGE_SECONDS:
        raise RuntimeError(f"BROKER_QUOTE_STALE:{sym}")
    if str(quote.get("source", "CTRADER_CBOT")).upper() not in ("CTRADER_CBOT", "CTRADER_STREAM"):
        raise RuntimeError(f"BROKER_QUOTE_SOURCE_INVALID:{sym}")

    bid = float(quote.get("bid") or 0.0)
    ask = float(quote.get("ask") or 0.0)
    if bid <= 0 or ask <= 0 or ask < bid:
        raise RuntimeError(f"BROKER_QUOTE_INVALID:{sym}")

    candles = get_broker_multi_timeframe_candles(sym, count=60)
    derived = _broker_indicators(candles, meta["digits"])
    price = round((bid + ask) / 2.0, meta["digits"])
    data = {
        "symbol": sym,
        "name": f"{meta['name']} (cTrader Broker)",
        "price": price,
        "bid": round(bid, meta["digits"]),
        "ask": round(ask, meta["digits"]),
        "spread": round(ask - bid, meta["digits"]),
        "pip_size": meta["pip"],
        **derived,
        "source": "CTRADER_CBOT",
        "candle_source": "CTRADER_CBOT",
        "quote_at": quote_at,
        "updated_at": now_ts,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    _FEED_CACHE[sym] = data
    _FEED_TIMESTAMPS[sym] = now_ts
    return data


def get_multi_timeframe_candles(symbol: str = "XAUUSD") -> Dict[str, Any]:
    """Return only cTrader broker candles and fail closed when unavailable."""
    return get_broker_multi_timeframe_candles(_clean_symbol(symbol), count=60)


def get_gold_market_snapshot(force_refresh: bool = False) -> Dict[str, Any]:
    return get_market_snapshot("XAUUSD", force_refresh=force_refresh)

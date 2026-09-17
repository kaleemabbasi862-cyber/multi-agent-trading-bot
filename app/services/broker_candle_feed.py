import json
import logging
import time
from typing import Any, Dict
from urllib.parse import urlencode
from urllib.request import urlopen

logger = logging.getLogger("TradeTalk.BrokerCandleFeed")
_TIMEFRAMES = ("M5", "M15", "H1", "H4", "D1")
_BRIDGE = "http://127.0.0.1:5001"
_EXPECTED_ACCOUNT = 5908018
_CACHE: Dict[str, Dict[str, Any]] = {}


def _get_json(path: str, timeout: float = 12.0) -> Any:
    with urlopen(_BRIDGE + path, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _validate_bridge() -> Dict[str, Any]:
    status = _get_json("/", 5.0)
    account_id = int(status.get("account_id") or 0)
    if account_id != _EXPECTED_ACCOUNT:
        raise RuntimeError(f"BROKER_CANDLE_ACCOUNT_MISMATCH:{account_id}")
    if bool(status.get("is_live")):
        raise RuntimeError("BROKER_CANDLE_LIVE_ACCOUNT_BLOCKED")
    return status


def get_broker_multi_timeframe_candles(symbol: str = "XAUUSD", count: int = 60) -> Dict[str, Any]:
    """Return cTrader cBot broker candles; fail closed and never use proxy feeds."""
    _validate_bridge()
    count = max(30, min(int(count), 500))
    result: Dict[str, Any] = {}
    for tf in _TIMEFRAMES:
        query = urlencode({"symbol": symbol.upper(), "timeframe": tf, "count": count})
        bars = _get_json("/candles?" + query)
        if not isinstance(bars, list):
            raise RuntimeError(f"BROKER_CANDLE_INVALID_RESPONSE:{tf}")
        bars = sorted(bars, key=lambda b: float(b.get("timestamp", 0)))
        if len(bars) < 30:
            raise RuntimeError(f"BROKER_CANDLE_INSUFFICIENT:{tf}:{len(bars)}")
        for bar in bars:
            if not all(k in bar for k in ("timestamp", "open", "high", "low", "close", "volume")):
                raise RuntimeError(f"BROKER_CANDLE_MALFORMED:{tf}")
        result[tf] = bars[-count:]
    _CACHE[symbol.upper()] = {"timestamp": time.time(), "candles": result}
    return result

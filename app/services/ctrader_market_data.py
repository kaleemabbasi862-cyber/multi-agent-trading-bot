import time
import datetime
import logging
from typing import Dict, Any, Optional, List
from app.services.symbol_resolver import symbol_resolver
from app.database.db import get_db_connection

logger = logging.getLogger("TradeTalk.cTraderMarketData")

class CTraderMarketDataEngine:
    """
    Real-time Market Data Engine handling cTrader spot price subscriptions,
    multi-timeframe candle formation, and historical trendbar caching.
    """
    def __init__(self):
        self._live_ticks: Dict[str, Dict[str, Any]] = {}
        self._trendbars_cache: Dict[str, List[Dict[str, Any]]] = {}

    def update_spot_tick(self, symbol: str, bid: float, ask: float, timestamp: Optional[float] = None):
        """Processes incoming spot price tick from cTrader Open API."""
        ts = timestamp or time.time()
        norm_sym = symbol_resolver.normalize_symbol(symbol)
        spread = round(abs(ask - bid), 4 if ("EUR" in norm_sym or "GBP" in norm_sym) else 2)
        mid = round((bid + ask) / 2.0, 5 if ("EUR" in norm_sym or "GBP" in norm_sym) else 2)

        tick_obj = {
            "symbol": norm_sym,
            "raw_symbol": symbol,
            "bid": bid,
            "ask": ask,
            "price": mid,
            "spread": spread,
            "timestamp": ts,
            "iso_time": datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat()
        }
        self._live_ticks[norm_sym] = tick_obj
        if "market_data_health_monitor" in globals():
            market_data_health_monitor.record_tick(symbol, tick_obj)

    def get_latest_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        norm_sym = symbol_resolver.normalize_symbol(symbol)
        return self._live_ticks.get(norm_sym)

    def save_trendbars_to_db(self, symbol: str, timeframe: str, candles: List[Dict[str, Any]]):
        """Persists historical candles into SQLite candles table."""
        norm_sym = symbol_resolver.normalize_symbol(symbol)
        with get_db_connection() as conn:
            for c in candles:
                ts_str = datetime.datetime.fromtimestamp(c["timestamp"] / 1000.0, datetime.timezone.utc).isoformat() if isinstance(c["timestamp"], (int, float)) and c["timestamp"] > 1e11 else str(c["timestamp"])
                try:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO candles
                        (symbol, timeframe, timestamp, open, high, low, close, volume)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (norm_sym, timeframe, ts_str, c["open"], c["high"], c["low"], c["close"], c.get("volume", 0.0))
                    )
                except Exception as e:
                    logger.debug(f"Candle write note: {e}")
            conn.commit()

    def get_cached_candles(self, symbol: str, timeframe: str = "15m", limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves cached candles from database."""
        norm_sym = symbol_resolver.normalize_symbol(symbol)
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM candles WHERE symbol = ? AND timeframe = ? ORDER BY timestamp DESC LIMIT ?",
                (norm_sym, timeframe, limit)
            ).fetchall()
            return [dict(r) for r in reversed(rows)]


class MarketDataHealthMonitor:
    """
    Continuous health monitor for cTrader real-time market data feed.
    Tracks last event timestamps, quote age, subscription status, and feed staleness.
    Fail-closed: Blocks new trades if quotes become stale.
    """
    def __init__(self, max_allowed_age_seconds: int = 30):
        self.max_allowed_age = max_allowed_age_seconds
        self.last_event_time: Dict[str, float] = {}
        self.last_valid_quote: Dict[str, Dict[str, Any]] = {}
        self.connection_state: str = "CONNECTED"
        self.subscribed_symbols: set = set()

    def record_tick(self, symbol: str, quote: Dict[str, Any]):
        """Records incoming quote event."""
        norm_sym = symbol_resolver.normalize_symbol(symbol)
        now = time.time()
        self.last_event_time[norm_sym] = now
        self.last_valid_quote[norm_sym] = quote
        self.subscribed_symbols.add(norm_sym)

    def get_quote_age(self, symbol: str) -> float:
        """Returns the age in seconds of the latest quote for the given symbol."""
        norm_sym = symbol_resolver.normalize_symbol(symbol)
        last_ts = self.last_event_time.get(norm_sym, 0.0)
        if last_ts <= 0:
            return 999999.0
        return round(time.time() - last_ts, 2)

    def is_quote_healthy(self, symbol: str, max_age: Optional[int] = None) -> Tuple[bool, str, float]:
        """
        Evaluates whether real-time market data is healthy and fresh.
        Returns (is_healthy, status_message, quote_age_seconds).
        """
        norm_sym = symbol_resolver.normalize_symbol(symbol)
        limit = max_age or self.max_allowed_age
        age = self.get_quote_age(norm_sym)

        if age >= 999999.0:
            return False, f"No market data received for {norm_sym}.", age
        if age > limit:
            return False, f"Market data stale: quote age {age:.1f}s exceeds limit ({limit}s).", age

        return True, "Market data is fresh and healthy.", age


ctrader_market_data = CTraderMarketDataEngine()
market_data_health_monitor = MarketDataHealthMonitor()


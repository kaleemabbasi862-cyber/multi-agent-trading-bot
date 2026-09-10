import time
import datetime
import logging
from typing import Dict, Any, Tuple, Optional, List
from app.services.symbol_resolver import symbol_resolver

logger = logging.getLogger("TradeTalk.MarketDataIntegrity")

class MarketDataIntegrityMonitor:
    """
    Production Market Data Integrity Monitor.
    Audits every live tick, quote, and candle against mathematical, temporal,
    and broker sanity rules. Enforces fail-closed execution on any anomaly.
    """

    PRICE_BOUNDS = {
        "XAUUSD": (1500.0, 10000.0),
        "GOLD": (1500.0, 10000.0),
        "EURUSD": (0.5000, 2.5000),
        "GBPUSD": (0.5000, 2.5000),
        "USDJPY": (50.0, 300.0),
        "AUDUSD": (0.3000, 1.5000),
        "USDCHF": (0.3000, 1.5000),
    }

    MAX_SPREAD_MAP = {
        "XAUUSD": 5.0, # $5.00 max spread on Gold
        "GOLD": 5.0,
        "EURUSD": 0.0010,
        "GBPUSD": 0.0015,
        "USDJPY": 0.10,
        "AUDUSD": 0.0010,
        "USDCHF": 0.0010,
    }

    def __init__(self, max_freshness_seconds: float = 5.0):
        self.max_freshness_seconds = max_freshness_seconds
        self._latest_ticks: Dict[str, Dict[str, Any]] = {}
        self._integrity_status: Dict[str, Dict[str, Any]] = {}
        self._connection_state: str = "CONNECTED"
        self._is_authenticated: bool = True
        self._anomaly_history: List[Dict[str, Any]] = []

    def set_connection_state(self, state: str, is_authenticated: bool = True):
        self._connection_state = state
        self._is_authenticated = is_authenticated

    def record_and_validate_tick(
        self,
        symbol: str,
        bid: float,
        ask: float,
        tick_timestamp: Optional[float] = None,
        broker_symbol_id: Optional[str] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates incoming live tick from broker feed and stores it if valid.
        Returns (is_valid, rejection_reason, telemetry).
        """
        receive_time = time.time()
        ts = tick_timestamp or receive_time
        norm_sym = symbol_resolver.normalize_symbol(symbol)

        # 1. FEED CONNECTION & AUTHENTICATION CHECK
        if self._connection_state != "CONNECTED" or not self._is_authenticated:
            reason = "FEED_DISCONNECT: Market data feed is disconnected or unauthenticated."
            self._log_anomaly(norm_sym, "FEED_DISCONNECT", reason)
            return False, reason, {"status": "FEED_DISCONNECT"}

        # 2. ZERO & NEGATIVE PRICE CHECKS
        if bid <= 0 or ask <= 0:
            err_type = "ZERO_PRICE" if (bid == 0 or ask == 0) else "NEGATIVE_PRICE"
            reason = f"{err_type}: Bid ({bid}) or Ask ({ask}) is non-positive."
            self._log_anomaly(norm_sym, err_type, reason)
            return False, reason, {"status": err_type, "bid": bid, "ask": ask}

        # 3. BID / ASK ORDER CHECK (Ask must be >= Bid)
        if ask < bid:
            reason = f"IMPOSSIBLE_PRICE: Inverted book: Ask ({ask}) is less than Bid ({bid})."
            self._log_anomaly(norm_sym, "IMPOSSIBLE_PRICE", reason)
            return False, reason, {"status": "IMPOSSIBLE_PRICE", "bid": bid, "ask": ask}

        # 4. SPREAD ANOMALY CHECK
        spread = round(ask - bid, 4 if ("EUR" in norm_sym or "GBP" in norm_sym) else 2)
        max_allowed_spread = self.MAX_SPREAD_MAP.get(norm_sym, 5.0)
        if spread <= 0 or spread > max_allowed_spread:
            reason = f"SPREAD_ANOMALY: Spread {spread} is outside valid range (0, {max_allowed_spread}]."
            self._log_anomaly(norm_sym, "SPREAD_ANOMALY", reason)
            return False, reason, {"status": "SPREAD_ANOMALY", "spread": spread, "max_allowed": max_allowed_spread}

        # 5. SANITY PRICE BOUNDS (Catch corrupted or stale cache prices)
        if norm_sym in self.PRICE_BOUNDS:
            min_p, max_p = self.PRICE_BOUNDS[norm_sym]
            if not (min_p <= bid <= max_p and min_p <= ask <= max_p):
                reason = f"IMPOSSIBLE_PRICE: Price ({bid}/{ask}) outside expected operational bounds ({min_p}, {max_p}) for {norm_sym}."
                self._log_anomaly(norm_sym, "IMPOSSIBLE_PRICE", reason)
                return False, reason, {"status": "IMPOSSIBLE_PRICE", "price": (bid + ask) / 2.0}

        # 6. TIMESTAMP FRESHNESS & CLOCK SKEW CHECK
        age = receive_time - ts
        if age > self.max_freshness_seconds:
            reason = f"STALE_PRICE: Tick age {age:.2f}s exceeds freshness limit ({self.max_freshness_seconds}s)."
            self._log_anomaly(norm_sym, "STALE_PRICE", reason)
            return False, reason, {"status": "STALE_PRICE", "age": age}
        if age < -10.0:
            reason = f"TIMESTAMP_ANOMALY: Future timestamp detected (skew = {abs(age):.2f}s)."
            self._log_anomaly(norm_sym, "TIMESTAMP_ANOMALY", reason)
            return False, reason, {"status": "TIMESTAMP_ANOMALY", "skew": age}

        # 7. TELEMETRY & STORE VALID TICK
        latency_ms = max(0.0, round((receive_time - ts) * 1000.0, 1))
        mid = round((bid + ask) / 2.0, 5 if ("EUR" in norm_sym or "GBP" in norm_sym) else 2)
        tick_record = {
            "symbol": norm_sym,
            "raw_symbol": symbol,
            "broker_symbol_id": broker_symbol_id or norm_sym,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "price": mid,
            "spread": spread,
            "tick_timestamp": ts,
            "receive_timestamp": receive_time,
            "feed_latency_ms": latency_ms,
            "connection_state": self._connection_state,
            "status": "HEALTHY",
            "iso_time": datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat()
        }

        self._latest_ticks[norm_sym] = tick_record
        self._integrity_status[norm_sym] = {
            "is_valid": True,
            "status": "HEALTHY",
            "last_checked": receive_time,
            "rejection_reason": None
        }
        return True, "TICK_INTEGRITY_PASSED", tick_record

    def evaluate_price_freshness(self, symbol: str, max_age: Optional[float] = None) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Evaluates whether current price for symbol is fresh, valid, and safe for trade decision.
        Fail-closed: Returns False if no data or data is stale.
        """
        norm_sym = symbol_resolver.normalize_symbol(symbol)
        limit = max_age or self.max_freshness_seconds
        tick = self._latest_ticks.get(norm_sym)

        if not tick:
            return False, f"NO_DATA: No validated live market tick recorded for {norm_sym}.", None

        age = time.time() - tick["receive_timestamp"]
        if age > limit:
            return False, f"STALE_PRICE: Market data age ({age:.2f}s) exceeds limit ({limit}s).", tick

        if self._connection_state != "CONNECTED":
            return False, "FEED_DISCONNECT: Broker feed disconnected.", tick

        return True, "FRESH_MARKET_DATA", tick

    def validate_candidate_price_against_feed(
        self,
        symbol: str,
        candidate_price: float,
        max_allowed_deviation_pips: float = 50.0
    ) -> Tuple[bool, str]:
        """
        Verifies that a candidate price proposed by an algorithm is consistent with
        the authoritative live broker tick, rejecting stale cache prices (e.g. $2884 vs $4400).
        """
        is_fresh, reason, tick = self.evaluate_price_freshness(symbol)
        if not is_fresh or not tick:
            return False, f"VETO_UNVERIFIED_PRICE: Cannot validate candidate price ({candidate_price}): {reason}"

        live_mid = tick["mid"]
        norm_sym = symbol_resolver.normalize_symbol(symbol)
        pip_unit = 0.10 if ("XAU" in norm_sym or "GOLD" in norm_sym or "JPY" in norm_sym) else 0.0001
        deviation_pips = abs(candidate_price - live_mid) / pip_unit

        if deviation_pips > max_allowed_deviation_pips:
            return False, f"VETO_PRICE_DEVIATION: Candidate price ${candidate_price:.2f} deviates {deviation_pips:.1f} pips from live broker mid ${live_mid:.2f} (max allowed {max_allowed_deviation_pips} pips)."

        return True, "PRICE_CONSISTENT_WITH_LIVE_FEED"

    def _log_anomaly(self, symbol: str, anomaly_type: str, reason: str):
        logger.error(f"[MarketDataIntegrity] 🚨 {symbol} {anomaly_type}: {reason}")
        self._anomaly_history.append({
            "timestamp": time.time(),
            "symbol": symbol,
            "type": anomaly_type,
            "reason": reason
        })
        self._integrity_status[symbol] = {
            "is_valid": False,
            "status": anomaly_type,
            "last_checked": time.time(),
            "rejection_reason": reason
        }

    def get_status(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        if symbol:
            norm_sym = symbol_resolver.normalize_symbol(symbol)
            return {
                "symbol": norm_sym,
                "tick": self._latest_ticks.get(norm_sym),
                "integrity": self._integrity_status.get(norm_sym, {"is_valid": False, "status": "UNINITIALIZED"}),
                "connection": self._connection_state
            }
        return {
            "connection": self._connection_state,
            "is_authenticated": self._is_authenticated,
            "symbols_monitored": list(self._latest_ticks.keys()),
            "recent_anomalies": self._anomaly_history[-10:]
        }

market_data_integrity_monitor = MarketDataIntegrityMonitor()

import logging
import math
from typing import Dict, Any, List, Optional
from app.services.symbol_resolver import symbol_resolver
from app.services.ctrader_market_data import ctrader_market_data

logger = logging.getLogger("TradeTalk.VolatilityEngine")

class VolatilityEngine:
    """
    Production Real-Time Volatility Adaptation Engine.
    Continuously tracks ATR across multiple timeframes (1M, 5M, 15M, 1H, 4H),
    calculates realized volatility, spread percentiles, and classifies volatility regimes.
    """

    DEFAULT_FALLBACK_ATR_POINTS = {
        "XAUUSD": 6.0,
        "GOLD": 6.0,
        "EURUSD": 0.0015,
        "GBPUSD": 0.0025,
        "USDJPY": 0.35,
        "AUDUSD": 0.0018,
        "USDCHF": 0.0018
    }

    def __init__(self):
        self._spread_history: Dict[str, List[float]] = {}
        self._volatility_state: Dict[str, Dict[str, Any]] = {}

    def calculate_atr(self, candles: List[Dict[str, Any]], period: int = 14) -> float:
        """Calculates Average True Range (ATR) from a list of OHLC candles."""
        if not candles or len(candles) < 2:
            return 0.0
        
        tr_list = []
        for i in range(1, len(candles)):
            curr = candles[i]
            prev = candles[i - 1]
            high = float(curr["high"])
            low = float(curr["low"])
            prev_close = float(prev["close"])
            
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)
            
        if not tr_list:
            return 0.0
            
        recent_tr = tr_list[-period:] if len(tr_list) >= period else tr_list
        return round(sum(recent_tr) / len(recent_tr), 4)

    def compute_multi_timeframe_volatility(self, symbol: str) -> Dict[str, Any]:
        """
        Calculates multi-timeframe ATR (1M, 5M, 15M, 1H, 4H), current regime,
        and adaptive stop buffers based on live market structure.
        """
        norm_sym = symbol_resolver.normalize_symbol(symbol)
        
        atr_1m = self.calculate_atr(ctrader_market_data.get_cached_candles(norm_sym, "1m", limit=30))
        atr_5m = self.calculate_atr(ctrader_market_data.get_cached_candles(norm_sym, "5m", limit=30))
        atr_15m = self.calculate_atr(ctrader_market_data.get_cached_candles(norm_sym, "15m", limit=30))
        atr_1h = self.calculate_atr(ctrader_market_data.get_cached_candles(norm_sym, "1h", limit=30))
        atr_4h = self.calculate_atr(ctrader_market_data.get_cached_candles(norm_sym, "4h", limit=30))

        # Base reference ATR is 15M, fallback to 1M or default point scale if empty
        ref_atr = atr_15m or atr_5m or atr_1m or self.DEFAULT_FALLBACK_ATR_POINTS.get(norm_sym, 5.0)

        # Classify Volatility Regime relative to symbol norm
        is_gold = "XAU" in norm_sym or "GOLD" in norm_sym
        if is_gold:
            if ref_atr < 2.5:
                regime = "LOW"
            elif ref_atr <= 7.0:
                regime = "NORMAL"
            elif ref_atr <= 15.0:
                regime = "HIGH"
            else:
                regime = "EXTREME"
        else:
            if ref_atr < 0.0008:
                regime = "LOW"
            elif ref_atr <= 0.0025:
                regime = "NORMAL"
            elif ref_atr <= 0.0060:
                regime = "HIGH"
            else:
                regime = "EXTREME"

        # Adaptive SL distance: 1.5x ATR(15M) bounded by structural sanity
        min_sl_dist = round(max(ref_atr * 1.0, 2.0 if is_gold else 0.0010), 2 if is_gold else 5)
        recommended_sl_dist = round(ref_atr * 1.5, 2 if is_gold else 5)

        state = {
            "symbol": norm_sym,
            "atr_1m": atr_1m,
            "atr_5m": atr_5m,
            "atr_15m": atr_15m,
            "atr_1h": atr_1h,
            "atr_4h": atr_4h,
            "reference_atr": ref_atr,
            "regime": regime,
            "min_structural_sl_distance": min_sl_dist,
            "recommended_sl_distance": recommended_sl_dist,
            "volatility_multiplier": 1.0 if regime == "NORMAL" else (0.75 if regime == "LOW" else (1.5 if regime == "HIGH" else 2.0))
        }

        self._volatility_state[norm_sym] = state
        return state

    def get_symbol_volatility(self, symbol: str) -> Dict[str, Any]:
        norm_sym = symbol_resolver.normalize_symbol(symbol)
        if norm_sym not in self._volatility_state:
            return self.compute_multi_timeframe_volatility(norm_sym)
        return self._volatility_state[norm_sym]

volatility_engine = VolatilityEngine()

import logging
from typing import Dict, Any, Tuple, List, Optional
from app.services.symbol_resolver import symbol_resolver
from app.services.ctrader_market_data import ctrader_market_data

logger = logging.getLogger("TradeTalk.StructuralExitEngine")

class StructuralExitEngine:
    """
    Production Structural Invalidation Engine.
    Evaluates open positions against true market structure on COMPLETED candles.
    Rules:
    - Never invalidates on a single tick, bid/ask spread noise, or sub-second indicator flip.
    - Requires completed 5M/15M candle closing beyond confirmed swing invalidation levels.
    """

    @classmethod
    def evaluate_structural_invalidation(
        cls,
        symbol: str,
        position_type: str,
        entry_price: float,
        initial_sl: float,
        timeframe: str = "5m"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Checks whether the market structure has definitively invalidated the trade thesis
        on completed candles (e.g. Bearish CHoCH for BUY, Bullish CHoCH for SELL).
        Returns (is_invalidated, exit_reason, telemetry).
        """
        norm_sym = symbol_resolver.normalize_symbol(symbol)
        pos_type = position_type.upper()

        candles = ctrader_market_data.get_cached_candles(norm_sym, timeframe=timeframe, limit=20)
        if len(candles) < 3:
            return False, "INSUFFICIENT_CANDLE_DATA", {"candles_count": len(candles)}

        # Analyze the latest COMPLETED candle (excluding the forming tick)
        completed_candle = candles[-1]
        c_close = float(completed_candle["close"])
        c_low = float(completed_candle["low"])
        c_high = float(completed_candle["high"])

        # Check completed candle close beyond initial structural invalidation level
        if pos_type == "BUY":
            # For BUY, invalidation requires a completed candle body closing below swing SL
            if initial_sl > 0 and c_close < initial_sl:
                reason = f"STRUCTURAL_INVALIDATION: Completed {timeframe} candle closed (${c_close:.2f}) below thesis invalidation level (${initial_sl:.2f})."
                logger.info(f"[StructuralExit] 🛑 {norm_sym} BUY Invalidated: {reason}")
                return True, reason, {"exit_model": "STRUCTURAL_INVALIDATION", "close_price": c_close, "invalidation_level": initial_sl}

        elif pos_type == "SELL":
            # For SELL, invalidation requires a completed candle body closing above swing SL
            if initial_sl > 0 and c_close > initial_sl:
                reason = f"STRUCTURAL_INVALIDATION: Completed {timeframe} candle closed (${c_close:.2f}) above thesis invalidation level (${initial_sl:.2f})."
                logger.info(f"[StructuralExit] 🛑 {norm_sym} SELL Invalidated: {reason}")
                return True, reason, {"exit_model": "STRUCTURAL_INVALIDATION", "close_price": c_close, "invalidation_level": initial_sl}

        return False, "STRUCTURE_INTACT", {"status": "HOLD"}

structural_exit_engine = StructuralExitEngine()

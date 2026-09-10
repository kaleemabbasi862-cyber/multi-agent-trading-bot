import math
from typing import List, Dict, Any, Optional, Tuple

class TechnicalIndicators:
    """
    Comprehensive Quantitative Technical Analysis Engine.
    Calculates RSI, MACD, EMA, SMA, VWAP, ATR, ADX, Bollinger Bands,
    Stochastic, Pivot Points, and Swing Highs/Lows with explainable signals.
    """

    @staticmethod
    def calculate_sma(prices: List[float], period: int) -> float:
        if not prices or len(prices) < period:
            return prices[-1] if prices else 0.0
        return sum(prices[-period:]) / period

    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> float:
        if not prices:
            return 0.0
        if len(prices) < period:
            return sum(prices) / len(prices)
        multiplier = 2.0 / (period + 1)
        ema = sum(prices[:period]) / period
        for p in prices[period:]:
            ema = (p - ema) * multiplier + ema
        return ema

    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> float:
        if len(prices) < period + 1:
            return 50.0
        gains, losses = [], []
        for i in range(1, len(prices)):
            diff = prices[i] - prices[i - 1]
            gains.append(max(0.0, diff))
            losses.append(max(0.0, -diff))

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0.0:
            return 100.0 if avg_gain > 0 else 50.0

        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return round(rsi, 2)

    @staticmethod
    def calculate_macd(
        prices: List[float],
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9
    ) -> Dict[str, float]:
        if len(prices) < slow_period + signal_period:
            return {"macd": 0.0, "signal": 0.0, "histogram": 0.0}

        # Calculate fast and slow EMAs across window
        macd_series = []
        multiplier_fast = 2.0 / (fast_period + 1)
        multiplier_slow = 2.0 / (slow_period + 1)

        ema_fast = sum(prices[:fast_period]) / fast_period
        ema_slow = sum(prices[:slow_period]) / slow_period

        # Walk through prices
        for i in range(slow_period, len(prices)):
            p = prices[i]
            ema_fast = (p - ema_fast) * multiplier_fast + ema_fast
            ema_slow = (p - ema_slow) * multiplier_slow + ema_slow
            macd_series.append(ema_fast - ema_slow)

        if len(macd_series) < signal_period:
            macd_val = macd_series[-1] if macd_series else 0.0
            return {"macd": round(macd_val, 4), "signal": round(macd_val, 4), "histogram": 0.0}

        # Signal line is EMA of MACD
        signal_line = TechnicalIndicators.calculate_ema(macd_series, signal_period)
        macd_line = macd_series[-1]
        hist = macd_line - signal_line

        return {
            "macd": round(macd_line, 4),
            "signal": round(signal_line, 4),
            "histogram": round(hist, 4)
        }

    @staticmethod
    def calculate_bollinger_bands(
        prices: List[float],
        period: int = 20,
        std_dev_mult: float = 2.0
    ) -> Dict[str, float]:
        if len(prices) < period:
            p = prices[-1] if prices else 0.0
            return {"upper": p, "middle": p, "lower": p, "bandwidth": 0.0}

        window = prices[-period:]
        sma = sum(window) / period
        variance = sum((x - sma) ** 2 for x in window) / period
        std_dev = math.sqrt(variance)

        upper = sma + (std_dev_mult * std_dev)
        lower = sma - (std_dev_mult * std_dev)
        bandwidth = ((upper - lower) / (sma + 1e-6)) * 100.0

        return {
            "upper": round(upper, 4),
            "middle": round(sma, 4),
            "lower": round(lower, 4),
            "bandwidth": round(bandwidth, 2)
        }

    @staticmethod
    def calculate_atr(candles: List[Dict[str, Any]], period: int = 14) -> float:
        """Calculates Average True Range (ATR)."""
        if len(candles) < 2:
            return 1.0
        tr_list = []
        for i in range(1, len(candles)):
            high = float(candles[i]["high"])
            low = float(candles[i]["low"])
            prev_close = float(candles[i - 1]["close"])
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)

        if len(tr_list) < period:
            return round(sum(tr_list) / len(tr_list), 4)
        return round(sum(tr_list[-period:]) / period, 4)

    @staticmethod
    def calculate_stochastic(
        candles: List[Dict[str, Any]],
        k_period: int = 14,
        d_period: int = 3
    ) -> Dict[str, float]:
        if len(candles) < k_period:
            return {"k": 50.0, "d": 50.0}

        k_values = []
        for i in range(k_period, len(candles) + 1):
            window = candles[i - k_period:i]
            highest_high = max(float(c["high"]) for c in window)
            lowest_low = min(float(c["low"]) for c in window)
            current_close = float(window[-1]["close"])

            rng = highest_high - lowest_low
            k = ((current_close - lowest_low) / (rng + 1e-6)) * 100.0
            k_values.append(k)

        current_k = k_values[-1] if k_values else 50.0
        current_d = sum(k_values[-d_period:]) / min(len(k_values), d_period) if k_values else 50.0

        return {
            "k": round(current_k, 2),
            "d": round(current_d, 2)
        }

    @staticmethod
    def calculate_adx(candles: List[Dict[str, Any]], period: int = 14) -> Dict[str, float]:
        """Calculates Average Directional Index (ADX), +DI, and -DI."""
        if len(candles) < period + 1:
            return {"adx": 25.0, "plus_di": 25.0, "minus_di": 25.0, "trend_strength": "MODERATE"}

        tr_list, plus_dm_list, minus_dm_list = [], [], []
        for i in range(1, len(candles)):
            h = float(candles[i]["high"])
            l = float(candles[i]["low"])
            ph = float(candles[i - 1]["high"])
            pl = float(candles[i - 1]["low"])
            pc = float(candles[i - 1]["close"])

            tr = max(h - l, abs(h - pc), abs(l - pc))
            tr_list.append(tr)

            up_move = h - ph
            down_move = pl - l

            plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
            minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0

            plus_dm_list.append(plus_dm)
            minus_dm_list.append(minus_dm)

        smooth_tr = sum(tr_list[-period:]) + 1e-6
        smooth_plus = sum(plus_dm_list[-period:])
        smooth_minus = sum(minus_dm_list[-period:])

        plus_di = (smooth_plus / smooth_tr) * 100.0
        minus_di = (smooth_minus / smooth_tr) * 100.0

        dx = (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-6)) * 100.0
        adx = round(dx, 2)

        strength = "STRONG" if adx >= 25.0 else ("VERY_STRONG" if adx >= 40.0 else "WEAK")

        return {
            "adx": adx,
            "plus_di": round(plus_di, 2),
            "minus_di": round(minus_di, 2),
            "trend_strength": strength
        }

    @staticmethod
    def calculate_vwap(candles: List[Dict[str, Any]]) -> float:
        """Calculates Volume Weighted Average Price (VWAP)."""
        if not candles:
            return 0.0
        cum_pv = 0.0
        cum_vol = 0.0
        for c in candles:
            typical_price = (float(c["high"]) + float(c["low"]) + float(c["close"])) / 3.0
            vol = float(c.get("volume", 1.0))
            if vol <= 0:
                vol = 1.0
            cum_pv += typical_price * vol
            cum_vol += vol
        return round(cum_pv / (cum_vol + 1e-6), 4)

    @staticmethod
    def calculate_pivot_points(high: float, low: float, close: float) -> Dict[str, float]:
        """Calculates Classic & Fibonacci Pivot Points."""
        pivot = (high + low + close) / 3.0
        r_range = high - low

        # Classic Pivots
        r1 = (2.0 * pivot) - low
        s1 = (2.0 * pivot) - high
        r2 = pivot + r_range
        s2 = pivot - r_range
        r3 = high + (2.0 * (pivot - low))
        s3 = low - (2.0 * (high - pivot))

        # Fibonacci Pivots
        fib_r1 = pivot + (0.382 * r_range)
        fib_s1 = pivot - (0.382 * r_range)
        fib_r2 = pivot + (0.618 * r_range)
        fib_s2 = pivot - (0.618 * r_range)
        fib_r3 = pivot + (1.000 * r_range)
        fib_s3 = pivot - (1.000 * r_range)

        return {
            "pivot": round(pivot, 4),
            "r1": round(r1, 4), "s1": round(s1, 4),
            "r2": round(r2, 4), "s2": round(s2, 4),
            "r3": round(r3, 4), "s3": round(s3, 4),
            "fib_r1": round(fib_r1, 4), "fib_s1": round(fib_s1, 4),
            "fib_r2": round(fib_r2, 4), "fib_s2": round(fib_s2, 4),
            "fib_r3": round(fib_r3, 4), "fib_s3": round(fib_s3, 4)
        }

    @staticmethod
    def detect_swing_points(candles: List[Dict[str, Any]], lookback: int = 3) -> Dict[str, Any]:
        """Detects swing highs and swing lows to classify Higher Highs, Higher Lows, etc."""
        if len(candles) < (lookback * 2) + 1:
            return {"swing_highs": [], "swing_lows": [], "structure": "UNCLEAR"}

        swing_highs = []
        swing_lows = []

        for i in range(lookback, len(candles) - lookback):
            current_h = float(candles[i]["high"])
            current_l = float(candles[i]["low"])

            # Swing High
            is_sh = all(current_h >= float(candles[i - j]["high"]) and current_h >= float(candles[i + j]["high"]) for j in range(1, lookback + 1))
            if is_sh:
                swing_highs.append({"index": i, "price": current_h, "timestamp": candles[i].get("timestamp")})

            # Swing Low
            is_sl = all(current_l <= float(candles[i - j]["low"]) and current_l <= float(candles[i + j]["low"]) for j in range(1, lookback + 1))
            if is_sl:
                swing_lows.append({"index": i, "price": current_l, "timestamp": candles[i].get("timestamp")})

        # Market Structure Classification
        structure = "RANGE"
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            last_sh, prev_sh = swing_highs[-1]["price"], swing_highs[-2]["price"]
            last_sl, prev_sl = swing_lows[-1]["price"], swing_lows[-2]["price"]

            if last_sh > prev_sh and last_sl > prev_sl:
                structure = "BULLISH_HH_HL" # Higher Highs, Higher Lows
            elif last_sh < prev_sh and last_sl < prev_sl:
                structure = "BEARISH_LH_LL" # Lower Highs, Lower Lows
            elif last_sh > prev_sh and last_sl <= prev_sl:
                structure = "EXPANDING"
            elif last_sh <= prev_sh and last_sl >= prev_sl:
                structure = "CONTRACTING_TRIANGLE"

        return {
            "swing_highs": swing_highs,
            "swing_lows": swing_lows,
            "structure": structure
        }


technical_indicators = TechnicalIndicators()

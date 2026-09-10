from typing import Dict, Any, List
from app.engine.technical_indicators import technical_indicators
from app.engine.smart_money_engine import smart_money_engine

class MultiTimeframeEngine:
    """
    Multi-Timeframe (MTF) Confluence Engine.
    Aggregates indicators and market structure across D1, H4, H1, M15, and M5 timeframes
    to generate unified direction and confidence score.
    """
    TIMEFRAME_WEIGHTS = {
        "D1": 0.25,   # Macro Trend & Major Bias
        "H4": 0.25,   # Intermediate Structure
        "H1": 0.20,   # Intraday Momentum & Key Levels
        "M15": 0.20,  # Trade Setup & Pattern Trigger
        "M5": 0.10    # Entry Confirmation & Sweeps
    }

    def evaluate_multi_timeframe(
        self,
        timeframe_candles: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, Any]:
        """
        Evaluates candles for multiple timeframes.
        Returns unified MTF direction, alignment score (0-100), and breakdown.
        """
        breakdown = {}
        weighted_bull_score = 0.0
        weighted_bear_score = 0.0
        total_weight = 0.0

        for tf, weight in self.TIMEFRAME_WEIGHTS.items():
            candles = timeframe_candles.get(tf, [])
            if not candles or len(candles) < 5:
                breakdown[tf] = {"trend": "NEUTRAL", "rsi": 50.0, "score": 50.0}
                continue

            closes = [float(c["close"]) for c in candles]
            current_p = closes[-1]
            ema_20 = technical_indicators.calculate_ema(closes, 20)
            ema_50 = technical_indicators.calculate_ema(closes, 50)
            rsi = technical_indicators.calculate_rsi(closes, 14)
            pd_zone = smart_money_engine.calculate_premium_discount(candles, period=30)

            bull_pts = 0.0
            bear_pts = 0.0

            # 1. Structural Trend & EMA Stack (50 points)
            if current_p >= ema_20 >= ema_50:
                bull_pts += 50.0
            elif current_p <= ema_20 <= ema_50:
                bear_pts += 50.0
            elif current_p >= ema_20:
                bull_pts += 30.0
                bear_pts += 10.0
            else:
                bear_pts += 30.0
                bull_pts += 10.0

            # 2. RSI Momentum (30 points)
            if rsi >= 55.0:
                bull_pts += 30.0
            elif rsi <= 45.0:
                bear_pts += 30.0
            else:
                bull_pts += 15.0
                bear_pts += 15.0

            # 3. Price Expansion / Slope (20 points)
            if closes[-1] > closes[0]:
                bull_pts += 20.0
            elif closes[-1] < closes[0]:
                bear_pts += 20.0
            else:
                bull_pts += 10.0
                bear_pts += 10.0

            if bull_pts >= bear_pts + 15.0:
                trend = "BULLISH"
                score = bull_pts
            elif bear_pts >= bull_pts + 15.0:
                trend = "BEARISH"
                score = bear_pts
            else:
                trend = "NEUTRAL"
                score = max(bull_pts, bear_pts)

            breakdown[tf] = {
                "trend": trend,
                "rsi": rsi,
                "ema_20": round(ema_20, 2),
                "ema_50": round(ema_50, 2),
                "zone": pd_zone["zone"],
                "score": round(score, 1)
            }

            if trend == "BULLISH":
                weighted_bull_score += (score * weight)
            elif trend == "BEARISH":
                weighted_bear_score += (score * weight)
            else:
                weighted_bull_score += (50.0 * weight)
                weighted_bear_score += (50.0 * weight)

            total_weight += weight

        final_bull = weighted_bull_score / (total_weight + 1e-6)
        final_bear = weighted_bear_score / (total_weight + 1e-6)

        if final_bull > final_bear + 10.0:
            consensus_trend = "BULLISH"
            confluence_score = round(final_bull, 1)
        elif final_bear > final_bull + 10.0:
            consensus_trend = "BEARISH"
            confluence_score = round(final_bear, 1)
        else:
            consensus_trend = "NO_TRADE_CONFLICT"
            confluence_score = round(max(final_bull, final_bear), 1)

        return {
            "consensus_trend": consensus_trend,
            "confluence_score": confluence_score,
            "is_aligned": consensus_trend in ("BULLISH", "BEARISH") and confluence_score >= 70.0,
            "timeframe_breakdown": breakdown
        }


multi_timeframe_engine = MultiTimeframeEngine()

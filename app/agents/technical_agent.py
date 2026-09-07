from typing import Dict, Any
from app.database.models import SignalPayload, AgentDecisionOutput

class TechnicalAnalystAgent:
    name: str = "Technical Analyst Agent"
    weight: float = 0.20

    def evaluate(self, signal: SignalPayload, market_data: Dict[str, Any]) -> AgentDecisionOutput:
        p = signal.entry_price
        act = signal.action.upper()
        ind = market_data.get("indicators", {})
        
        rsi_15m = float(ind.get("rsi", 50.0))
        ema_20_15m = float(ind.get("ema_20", p))
        ema_50_15m = float(ind.get("ema_50", p))
        ema_200_15m = float(ind.get("ema_200", p))
        ema_20_1h = float(ind.get("ema_20_1h", p))
        ema_50_1h = float(ind.get("ema_50_1h", p))
        trend_1h = ind.get("trend_1h", "BULLISH")
        support = float(ind.get("support", p - 8.0))
        resistance = float(ind.get("resistance", p + 8.0))
        
        reasons = []
        score = 70.0
        direction = "NEUTRAL"
        
        # 1. 1H Multi-Timeframe Alignment Check
        is_1h_bull = (trend_1h == "BULLISH" or ema_20_1h >= ema_50_1h)
        is_1h_bear = (trend_1h == "BEARISH" or ema_20_1h <= ema_50_1h)
        
        if act == "BUY":
            direction = "BUY"
            if is_1h_bull:
                score += 15.0
                reasons.append(f"1H Trend Aligned BULLISH (EMA20: ${ema_20_1h:.2f} >= EMA50: ${ema_50_1h:.2f})")
            else:
                score -= 35.0
                reasons.append(f"1H Trend MISALIGNED (1H is {trend_1h})")
                
            # 15m EMAs Check
            if p >= ema_20_15m >= ema_50_15m:
                score += 10.0
                reasons.append("15m Price above EMA20 and EMA50 (Strong Bullish Stack)")
            elif p < ema_50_15m:
                score -= 15.0
                reasons.append("15m Price below EMA50")
                
            # RSI Momentum Check
            if 45.0 <= rsi_15m <= 68.0:
                score += 5.0
                reasons.append(f"RSI 14 in optimal expansion zone ({rsi_15m:.1f})")
            elif rsi_15m > 75.0:
                score -= 20.0
                reasons.append(f"RSI 14 Overbought ({rsi_15m:.1f}) - Pullback risk")
            elif rsi_15m < 35.0:
                score -= 15.0
                reasons.append(f"RSI 14 Weak Bearish Momentum ({rsi_15m:.1f})")
                
        elif act == "SELL":
            direction = "SELL"
            if is_1h_bear:
                score += 15.0
                reasons.append(f"1H Trend Aligned BEARISH (EMA20: ${ema_20_1h:.2f} <= EMA50: ${ema_50_1h:.2f})")
            else:
                score -= 35.0
                reasons.append(f"1H Trend MISALIGNED (1H is {trend_1h})")
                
            # 15m EMAs Check
            if p <= ema_20_15m <= ema_50_15m:
                score += 10.0
                reasons.append("15m Price below EMA20 and EMA50 (Strong Bearish Stack)")
            elif p > ema_50_15m:
                score -= 15.0
                reasons.append("15m Price above EMA50")
                
            # RSI Momentum Check
            if 32.0 <= rsi_15m <= 55.0:
                score += 5.0
                reasons.append(f"RSI 14 in optimal bearish expansion zone ({rsi_15m:.1f})")
            elif rsi_15m < 25.0:
                score -= 20.0
                reasons.append(f"RSI 14 Oversold ({rsi_15m:.1f}) - Reversal risk")
            elif rsi_15m > 65.0:
                score -= 15.0
                reasons.append(f"RSI 14 Strong Bullish Momentum ({rsi_15m:.1f})")

        score = max(0.0, min(100.0, score))
        decision = "PASS" if score >= 80.0 else ("FAIL" if score < 60.0 else "NEUTRAL")
        
        summary = (
            f"Technical Score: {score:.1f}/100. "
            + "; ".join(reasons)
            + f" | S/R Bounds: [${support:.2f} - ${resistance:.2f}]"
        )
        
        return AgentDecisionOutput(
            agent_name=self.name,
            direction=direction,
            score=score,
            decision=decision,
            reasoning_summary=summary,
            metrics={
                "rsi_15m": rsi_15m,
                "ema_20_15m": ema_20_15m,
                "ema_50_15m": ema_50_15m,
                "ema_200_15m": ema_200_15m,
                "ema_20_1h": ema_20_1h,
                "ema_50_1h": ema_50_1h,
                "trend_1h": trend_1h,
                "support": support,
                "resistance": resistance
            }
        )

technical_agent = TechnicalAnalystAgent()

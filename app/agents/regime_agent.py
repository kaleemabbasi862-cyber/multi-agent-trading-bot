from typing import Dict, Any
from app.database.models import SignalPayload, AgentDecisionOutput

class MarketRegimeAgent:
    name: str = "Market Regime Agent"
    weight: float = 0.15

    def evaluate(self, signal: SignalPayload, market_data: Dict[str, Any]) -> AgentDecisionOutput:
        p = signal.entry_price
        act = signal.action.upper()
        ind = market_data.get("indicators", {})
        
        rsi = float(ind.get("rsi", 50.0))
        ema_20 = float(ind.get("ema_20", p))
        ema_50 = float(ind.get("ema_50", p))
        ema_200 = float(ind.get("ema_200", p))
        support = float(ind.get("support", p - 8.0))
        resistance = float(ind.get("resistance", p + 8.0))
        
        # Calculate market spread & range depth
        range_span = abs(resistance - support)
        ema_spread = abs(ema_20 - ema_50)
        
        # Classify Regime
        if ema_20 > ema_50 > ema_200 and rsi >= 55.0:
            regime = "STRONG_UPTREND"
        elif ema_20 > ema_50 and rsi >= 50.0:
            regime = "WEAK_UPTREND"
        elif ema_20 < ema_50 < ema_200 and rsi <= 45.0:
            regime = "STRONG_DOWNTREND"
        elif ema_20 < ema_50 and rsi <= 50.0:
            regime = "WEAK_DOWNTREND"
        elif range_span < 5.0 and abs(p - ema_50) < 1.5:
            regime = "RANGE"
        elif range_span > 25.0:
            regime = "HIGH_VOLATILITY"
        else:
            regime = "BREAKOUT"

        reasons = []
        score = 80.0
        direction = "NEUTRAL"
        
        if regime in ("STRONG_UPTREND", "WEAK_UPTREND"):
            if act == "BUY":
                score += 15.0
                direction = "BUY"
                reasons.append(f"Regime {regime} is highly supportive of Bullish Trend Follow")
            else:
                score -= 30.0
                reasons.append(f"Regime {regime} conflicts with Counter-Trend Short")
        elif regime in ("STRONG_DOWNTREND", "WEAK_DOWNTREND"):
            if act == "SELL":
                score += 15.0
                direction = "SELL"
                reasons.append(f"Regime {regime} is highly supportive of Bearish Trend Follow")
            else:
                score -= 30.0
                reasons.append(f"Regime {regime} conflicts with Counter-Trend Long")
        elif regime == "RANGE":
            score -= 25.0
            reasons.append(f"Regime {regime} warning: Choppy consolidation. Trend-following signals have low win rate in tight range.")
        elif regime == "HIGH_VOLATILITY":
            score -= 10.0
            reasons.append(f"Regime {regime}: Wide swings observed. Strict SL enforcement required.")
        elif regime == "BREAKOUT":
            score += 10.0
            direction = act
            reasons.append("Breakout structural momentum confirmed.")

        score = max(0.0, min(100.0, score))
        decision = "PASS" if score >= 80.0 else ("FAIL" if score < 60.0 else "NEUTRAL")
        summary = f"Regime: {regime} (Score: {score:.1f}/100). " + "; ".join(reasons)
        
        return AgentDecisionOutput(
            agent_name=self.name,
            direction=direction,
            score=score,
            decision=decision,
            reasoning_summary=summary,
            metrics={
                "regime": regime,
                "range_span": round(range_span, 2),
                "ema_spread": round(ema_spread, 2)
            }
        )

regime_agent = MarketRegimeAgent()

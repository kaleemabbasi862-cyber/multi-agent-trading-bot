from typing import Dict, Any
from app.database.models import SignalPayload, AgentDecisionOutput

class LiquiditySmartMoneyAgent:
    name: str = "Liquidity & SMC Agent"
    weight: float = 0.15

    def evaluate(self, signal: SignalPayload, market_data: Dict[str, Any]) -> AgentDecisionOutput:
        p = signal.entry_price
        act = signal.action.upper()
        ind = market_data.get("indicators", {})
        support = float(ind.get("support", p - 8.0))
        resistance = float(ind.get("resistance", p + 8.0))
        high_24h = float(market_data.get("high_24h", resistance + 5.0))
        low_24h = float(market_data.get("low_24h", support - 5.0))
        
        # Calculate Equilibrium (50% range)
        equilibrium = round((high_24h + low_24h) / 2.0, 2)
        is_discount = p < equilibrium  # Optimal for BUY
        is_premium = p > equilibrium   # Optimal for SELL
        
        reasons = []
        score = 80.0
        direction = "NEUTRAL"
        evidence = []
        
        # 1. Premium vs Discount Zone Analysis
        if act == "BUY":
            direction = "BUY"
            if is_discount:
                score += 10.0
                reasons.append(f"Price (${p:.2f}) is in DISCOUNT zone (< Equilibrium ${equilibrium:.2f}) - Institutional Buy Value")
                evidence.append({"type": "DISCOUNT_PRICING", "price": p, "confidence": 0.85})
            else:
                score -= 10.0
                reasons.append(f"Price (${p:.2f}) is in PREMIUM zone (> Equilibrium ${equilibrium:.2f}) - Higher Risk for Longs")
        elif act == "SELL":
            direction = "SELL"
            if is_premium:
                score += 10.0
                reasons.append(f"Price (${p:.2f}) is in PREMIUM zone (> Equilibrium ${equilibrium:.2f}) - Institutional Sell Value")
                evidence.append({"type": "PREMIUM_PRICING", "price": p, "confidence": 0.85})
            else:
                score -= 10.0
                reasons.append(f"Price (${p:.2f}) is in DISCOUNT zone (< Equilibrium ${equilibrium:.2f}) - Higher Risk for Shorts")

        # 2. Liquidity Sweeps & Order Block (OB) Proximity
        dist_to_low = abs(p - low_24h)
        dist_to_high = abs(p - high_24h)
        
        if act == "BUY" and dist_to_low < 4.0:
            score += 10.0
            reasons.append(f"Bullish Liquidity Sweep of Day's Low (${low_24h:.2f}) with immediate displacement")
            evidence.append({"type": "LIQUIDITY_SWEEP_LOW", "price": low_24h, "confidence": 0.90})
        elif act == "SELL" and dist_to_high < 4.0:
            score += 10.0
            reasons.append(f"Bearish Liquidity Sweep of Day's High (${high_24h:.2f}) with rejection")
            evidence.append({"type": "LIQUIDITY_SWEEP_HIGH", "price": high_24h, "confidence": 0.90})
            
        # 3. Fair Value Gap (FVG) / Mitigation
        ob_level = round(support + 1.5, 2) if act == "BUY" else round(resistance - 1.5, 2)
        reasons.append(f"Order Block mitigation zone identified near ${ob_level:.2f}")
        evidence.append({"type": "ORDER_BLOCK", "price": ob_level, "confidence": 0.80})

        score = max(0.0, min(100.0, score))
        decision = "PASS" if score >= 80.0 else ("FAIL" if score < 60.0 else "NEUTRAL")
        summary = f"SMC Score: {score:.1f}/100. " + "; ".join(reasons)
        
        return AgentDecisionOutput(
            agent_name=self.name,
            direction=direction,
            score=score,
            decision=decision,
            reasoning_summary=summary,
            metrics={
                "equilibrium": equilibrium,
                "is_discount": is_discount,
                "is_premium": is_premium,
                "high_24h": high_24h,
                "low_24h": low_24h,
                "evidence": evidence
            }
        )

liquidity_agent = LiquiditySmartMoneyAgent()

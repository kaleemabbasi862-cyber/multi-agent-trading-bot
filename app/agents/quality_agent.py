from typing import Dict, Any
from app.database.models import SignalPayload, AgentDecisionOutput

class TradeQualityAgent:
    name: str = "Trade Quality Agent"
    weight: float = 0.15
    min_sample_size: int = 20

    def evaluate(self, signal: SignalPayload, historical_stats: Dict[str, Any], market_data: Dict[str, Any]) -> AgentDecisionOutput:
        p = signal.entry_price
        sl = signal.stop_loss
        tp = signal.take_profit
        act = signal.action.upper()
        
        sl_dist = abs(p - sl)
        tp_dist = abs(tp - p)
        rr = round(tp_dist / (sl_dist + 1e-6), 2)
        
        total_samples = int(historical_stats.get("closed_trades", 0))
        win_rate = float(historical_stats.get("win_rate", 65.0))
        profit_factor = float(historical_stats.get("profit_factor", 1.6))
        
        reasons = []
        score = 80.0
        direction = act
        
        # 1. Statistical Confidence & Sample Size Gate
        if total_samples < self.min_sample_size:
            reasons.append(f"Small historical sample ({total_samples}/{self.min_sample_size} trades). Using calibrated baseline quality score.")
            score = 82.0
        else:
            if win_rate >= 60.0 and profit_factor >= 1.5:
                score += 10.0
                reasons.append(f"Strong historical setup match: Win Rate {win_rate:.1f}%, Profit Factor {profit_factor:.2f}")
            elif win_rate < 45.0 or profit_factor < 1.0:
                score -= 20.0
                reasons.append(f"Weak historical expectancy: Win Rate {win_rate:.1f}%, Profit Factor {profit_factor:.2f}")
                
        # 2. Risk-Reward Efficiency
        if rr >= 2.5:
            score += 8.0
            reasons.append(f"High-quality asymmetric R:R (1:{rr:.2f})")
        elif rr >= 2.0:
            score += 4.0
            reasons.append(f"Standard sniper R:R (1:{rr:.2f})")
        else:
            score -= 15.0
            reasons.append(f"Sub-optimal R:R (1:{rr:.2f})")

        score = max(0.0, min(100.0, score))
        decision = "PASS" if score >= 80.0 else ("FAIL" if score < 60.0 else "NEUTRAL")
        summary = f"Quality Score: {score:.1f}/100. " + "; ".join(reasons)
        
        return AgentDecisionOutput(
            agent_name=self.name,
            direction=direction,
            score=score,
            decision=decision,
            reasoning_summary=summary,
            metrics={
                "rr_ratio": rr,
                "historical_sample_size": total_samples,
                "historical_win_rate": win_rate,
                "historical_profit_factor": profit_factor,
                "min_sample_size_required": self.min_sample_size
            }
        )

quality_agent = TradeQualityAgent()

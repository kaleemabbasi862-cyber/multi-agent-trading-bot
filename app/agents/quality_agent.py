import time
import datetime
from typing import Dict, Any
from app.database.models import (
    SignalPayload,
    AgentDecisionOutput,
    AgentOperationalCriticality,
    AgentHealthStatus
)

class TradeQualityAgent:
    name: str = "Trade Quality Agent"
    weight: float = 3 / 17
    criticality: str = AgentOperationalCriticality.DECISION_CRITICAL
    min_sample_size: int = 20

    def evaluate(self, signal: SignalPayload, historical_stats: Dict[str, Any], market_data: Dict[str, Any]) -> AgentDecisionOutput:
        t_start = time.time()
        start_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        p = float(signal.entry_price or 0.0)
        sl = float(signal.stop_loss or 0.0)
        tp = float(signal.take_profit or 0.0)
        act = (signal.action or "").upper()
        
        if p <= 0.0 or sl <= 0.0 or tp <= 0.0:
            end_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            return AgentDecisionOutput(
                agent_name=self.name,
                direction="NEUTRAL",
                score=0.0,
                decision="FAIL",
                reasoning_summary="INVALID_INPUT: Signal entry, SL, or TP non-positive.",
                operational_criticality=self.criticality,
                health_status=AgentHealthStatus.INVALID_INPUT,
                execution_started_at=start_iso,
                execution_completed_at=end_iso,
                execution_latency_ms=round((time.time() - t_start) * 1000, 2),
                data_source="Database Historical Ledger / Indicators",
                confidence=0.0,
                error="Invalid price coordinates in signal"
            )

        ind = market_data.get("indicators", {}) if market_data else {}
        spread = float(market_data.get("spread", 0.35)) if market_data else 0.35
        rsi_val = float(ind.get("rsi", 50.0))
        
        sl_dist = abs(p - sl)
        tp_dist = abs(tp - p)
        rr = round(tp_dist / (sl_dist + 1e-6), 2)
        
        total_samples = int(historical_stats.get("closed_trades", 0)) if historical_stats else 0
        has_sufficient_samples = total_samples >= self.min_sample_size
        
        reasons = []
        score = 75.0
        direction = act
        health_status = AgentHealthStatus.HEALTHY
        
        # 1. Statistical Expectancy Evaluation
        if has_sufficient_samples:
            win_rate = float(historical_stats.get("win_rate", 50.0))
            profit_factor = float(historical_stats.get("profit_factor", 1.0))
            win_prob = max(0.10, min(0.90, win_rate / 100.0))
            expectancy = (win_prob * rr) - ((1.0 - win_prob) * 1.0)
            
            if profit_factor >= 1.5 or expectancy > 0.20:
                score += 10.0
                reasons.append(f"Empirical statistical edge: PF {profit_factor:.2f}, Exp +{expectancy:.2f}R (N={total_samples})")
            elif profit_factor >= 1.1 or expectancy >= 0.0:
                score += 5.0
                reasons.append(f"Positive empirical expectancy: PF {profit_factor:.2f} (N={total_samples})")
            else:
                score -= 10.0
                reasons.append(f"Sub-par historical expectancy: PF {profit_factor:.2f} (N={total_samples})")
        else:
            # Baseline mathematical expectancy assuming neutral 50% hit rate with R:R
            win_rate = 50.0
            profit_factor = 1.0
            expectancy = (0.50 * rr) - (0.50 * 1.0)
            health_status = AgentHealthStatus.DEGRADED
            reasons.append(f"INSUFFICIENT_SAMPLE: Closed trades N={total_samples} < {self.min_sample_size}. Relying on structural R:R expectancy.")

        # 2. Risk-Reward Efficiency
        if rr >= 2.5:
            score += 10.0
            reasons.append(f"High-conviction asymmetric R:R (1:{rr:.2f})")
        elif rr >= 1.95:
            score += 5.0
            reasons.append(f"Target Sniper R:R profile (1:{rr:.2f})")
        else:
            score -= 20.0
            reasons.append(f"Sub-optimal R:R (1:{rr:.2f}) below 1:2.0 target")

        # 3. Spread-to-Risk Execution Efficiency
        spread_to_sl_pct = (spread / (sl_dist + 1e-6)) * 100.0
        if spread_to_sl_pct < 6.0:
            score += 5.0
            reasons.append(f"Tight spread friction ({spread_to_sl_pct:.1f}% of SL)")
        elif spread_to_sl_pct > 15.0:
            score -= 15.0
            reasons.append(f"High spread drag ({spread_to_sl_pct:.1f}% of SL)")

        # 4. Momentum Quality Filter
        if (act == "BUY" and 45.0 <= rsi_val <= 65.0) or (act == "SELL" and 35.0 <= rsi_val <= 55.0):
            score += 5.0
            reasons.append(f"Optimal momentum corridor (RSI: {rsi_val:.1f})")

        score = max(0.0, min(100.0, score))
        decision = "PASS" if score >= 65.0 else ("FAIL" if score < 45.0 else "NEUTRAL")
        summary = f"Quality Score: {score:.1f}/100. " + "; ".join(reasons)
        
        end_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        latency_ms = round((time.time() - t_start) * 1000, 2)
        
        return AgentDecisionOutput(
            agent_name=self.name,
            direction=direction,
            score=score,
            decision=decision,
            reasoning_summary=summary,
            operational_criticality=self.criticality,
            health_status=health_status,
            execution_started_at=start_iso,
            execution_completed_at=end_iso,
            execution_latency_ms=latency_ms,
            data_source="Database Ledger & cTrader Indicators",
            confidence=score,
            metrics={
                "rr_ratio": rr,
                "expectancy_r": round(expectancy, 2),
                "historical_sample_size": total_samples,
                "historical_win_rate": win_rate,
                "historical_profit_factor": profit_factor,
                "spread_to_sl_pct": round(spread_to_sl_pct, 1),
                "sufficient_sample": has_sufficient_samples
            }
        )

quality_agent = TradeQualityAgent()


from typing import List, Dict, Any, Tuple
import settings_manager
from app.config import settings
from app.database.models import SignalPayload, AgentDecisionOutput, RiskCheckResult

class HeadDeskManagerAgent:
    name: str = "Head Desk Manager"

    # Default Quantitative Weights
    WEIGHTS = {
        "Technical Analyst Agent": 0.20,
        "Fundamental & Sentiment Agent": 0.15,
        "Market Regime Agent": 0.15,
        "Liquidity & SMC Agent": 0.15,
        "Trade Quality Agent": 0.15,
        "Risk Management Agent": 0.20
    }

    def arbitrate(
        self,
        signal: SignalPayload,
        agent_decisions: List[AgentDecisionOutput],
        risk_check: RiskCheckResult,
        guardian_veto: bool = False,
        guardian_reason: str = None
    ) -> Tuple[str, float, str]:
        """
        Arbitrates final decision using weighted scoring & non-negotiable Risk Veto rules:
        - Returns (decision_status, decision_score, final_explanation)
        - Decision statuses: APPROVED, CONDITIONAL, WATCHLIST, REJECTED, BLOCKED
        """
        total_score = 0.0
        total_weight = 0.0
        veto_triggered = False
        veto_reasons = []

        for dec in agent_decisions:
            w = self.WEIGHTS.get(dec.agent_name, 0.10)
            total_score += dec.score * w
            total_weight += w
            
            if dec.decision == "VETO":
                veto_triggered = True
                veto_reasons.append(f"[{dec.agent_name}] {dec.reasoning_summary}")

        if not risk_check.passed:
            veto_triggered = True
            veto_reasons.append(f"[Risk Veto] {risk_check.veto_reason}")

        if guardian_veto:
            veto_triggered = True
            veto_reasons.append(f"[No-Trade Guardian] {guardian_reason}")

        final_score = round(total_score / (total_weight + 1e-6), 1)

        # 1. Hard Veto overrides all positive votes
        if veto_triggered:
            decision_status = "BLOCKED"
            final_explanation = (
                f"[DECISION: BLOCKED] 🚫 Trade Execution Halted by Safety Veto Gate.\n"
                f"• Decision Confidence Score: {final_score}/100\n"
                f"• Critical Veto Reasons:\n  - " + "\n  - ".join(veto_reasons)
            )
            return decision_status, final_score, final_explanation

        # 2. Strict Multi-Agent Consensus Evaluation (At least 5 of 7 agents > 80%)
        min_agents_required = getattr(settings, "MIN_CONSENSUS_AGENTS", 5)
        min_confidence = getattr(settings, "MIN_AGENT_CONFIDENCE", 80.0)

        agreeing_agents = [
            d for d in agent_decisions 
            if (d.direction in (signal.action, "PASS", "BUY" if signal.action == "BUY" else "SELL") or d.decision == "PASS")
            and d.score >= min_confidence
        ]
        
        # General's vote counts as the 7th arbiter if aggregate score >= threshold
        general_agrees = (final_score >= min_confidence)
        total_agreeing = len(agreeing_agents) + (1 if general_agrees else 0)

        vol = getattr(signal, "volume", 0.01) or 0.01
        lot_str = f"{vol:.2f} Lots"
        sym_str = getattr(signal, "symbol", "XAUUSD") or "XAUUSD"

        if total_agreeing >= min_agents_required and final_score >= min_confidence and risk_check.passed:
            decision_status = "APPROVED"
            final_explanation = (
                f"[DECISION: APPROVED — HIGH CONVICTION] 🎯 [CONSENSUS CLEARANCE GRANTED]\n"
                f"• Multi-Agent Consensus: {total_agreeing}/7 Agents in Full Agreement (>= {min_agents_required} Required)\n"
                f"• Aggregate Decision Confidence Score: {final_score}% (Threshold >= {int(min_confidence)}% Met)\n"
                f"• Risk-to-Reward: 1:{risk_check.rr_ratio:.2f} (>= 1:2.0 Verified) | Protected SL: ${signal.stop_loss:.2f} | TP: ${signal.take_profit:.2f}\n"
                f"• {lot_str} on {sym_str} approved for live execution."
            )
        else:
            decision_status = f"BLOCKED ({total_agreeing}/7 Consensus)"
            final_explanation = (
                f"[DECISION: BLOCKED — INSUFFICIENT CONSENSUS] 🚫 [EXECUTION HALTED]\n"
                f"• Multi-Agent Agreement: {total_agreeing}/7 Agents Agreed (Requires at least {min_agents_required}/7 with score >= {int(min_confidence)}%)\n"
                f"• Aggregate Decision Score: {final_score}%\n"
                f"• Capital preserved. Trade rejected until strict 5-agent quantitative agreement is achieved."
            )

        return decision_status, final_score, final_explanation

head_desk_agent = HeadDeskManagerAgent()

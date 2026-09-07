from typing import List, Dict, Any, Tuple
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

        # 2. Score-Based Categorization
        if final_score >= settings.HIGH_QUALITY_SCORE and risk_check.passed:
            decision_status = "APPROVED"
            final_explanation = (
                f"[DECISION: APPROVED — HIGH QUALITY] 🎯 Setup fully confirmed by all 7 quantitative agents.\n"
                f"• Decision Confidence Score: {final_score}% (Tier-1 Quality Score >= {settings.HIGH_QUALITY_SCORE}%)\n"
                f"• Risk-to-Reward: 1:{risk_check.rr_ratio:.2f} | Protected SL: ${signal.stop_loss:.2f} | TP: ${signal.take_profit:.2f}\n"
                f"• Dispatched for immediate execution."
            )
        elif final_score >= settings.MIN_DECISION_SCORE and risk_check.passed:
            decision_status = "APPROVED"
            final_explanation = (
                f"[DECISION: APPROVED — STANDARD] 🎯 Setup satisfies sniper conviction thresholds.\n"
                f"• Decision Confidence Score: {final_score}% (Score >= {settings.MIN_DECISION_SCORE}%)\n"
                f"• Risk-to-Reward: 1:{risk_check.rr_ratio:.2f} | 0.01 Lots XAUUSD\n"
                f"• Dispatched for immediate execution."
            )
        elif 75.0 <= final_score < settings.MIN_DECISION_SCORE:
            decision_status = "WATCHLIST"
            final_explanation = (
                f"[DECISION: WATCHLIST / WAIT] ⏳ Moderate conviction. Candidate flagged for monitoring.\n"
                f"• Decision Confidence Score: {final_score}% (Requires >= {settings.MIN_DECISION_SCORE}% for automatic execution)\n"
                f"• Capital preserved. Awaiting tighter structural alignment."
            )
        else:
            decision_status = "REJECTED"
            final_explanation = (
                f"[DECISION: REJECTED] ❌ Insufficient edge or contradictory agent consensus.\n"
                f"• Decision Confidence Score: {final_score}% (Below 75.0% threshold)\n"
                f"• Signal discarded."
            )

        return decision_status, final_score, final_explanation

head_desk_agent = HeadDeskManagerAgent()

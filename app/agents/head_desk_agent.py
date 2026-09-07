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

        # 2. Dynamic Score-Based Categorization (Configurable via Settings Manager, Default 75%)
        try:
            threshold = float(settings_manager.get_min_confidence_threshold())
        except Exception:
            threshold = 75.0

        vol = getattr(signal, "volume", 0.01) or 0.01
        lot_str = f"{vol:.2f} Lots"
        sym_str = getattr(signal, "symbol", "XAUUSD") or "XAUUSD"

        if final_score >= threshold and risk_check.passed:
            tier = "TIER 1" if final_score >= max(threshold + 10.0, 85.0) else "STANDARD"
            decision_status = "APPROVED"
            final_explanation = (
                f"[DECISION: APPROVED — {tier}] 🎯 [CONSENSUS CLEARANCE GRANTED]\n"
                f"• Decision Confidence Score: {final_score}% (Threshold >= {int(threshold)}% Met)\n"
                f"• Risk-to-Reward: 1:{risk_check.rr_ratio:.2f} (>= 1:2.0 Verified) | Protected SL: ${signal.stop_loss:.2f} | TP: ${signal.take_profit:.2f}\n"
                f"• {lot_str} on {sym_str} approved for immediate execution."
            )
        elif (threshold - 10.0) <= final_score < threshold:
            decision_status = f"BLOCKED (<{int(threshold)}% Conviction)"
            final_explanation = (
                f"[DECISION: BLOCKED — CONVICTION < {int(threshold)}%] 🚫 [EXECUTION HALTED]\n"
                f"• Decision Confidence Score: {final_score}% (Requires >= {int(threshold)}% for automatic execution)\n"
                f"• Capital preserved. Trade rejected until >= {int(threshold)}% consensus conviction is reached."
            )
        else:
            decision_status = "REJECTED"
            final_explanation = (
                f"[DECISION: REJECTED] ❌ Insufficient edge or contradictory agent consensus.\n"
                f"• Decision Confidence Score: {final_score}% (Below {int(threshold)}% threshold)\n"
                f"• Signal discarded."
            )

        return decision_status, final_score, final_explanation

        return decision_status, final_score, final_explanation

head_desk_agent = HeadDeskManagerAgent()

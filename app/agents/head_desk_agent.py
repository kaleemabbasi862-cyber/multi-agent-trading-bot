import time
import datetime
from typing import List, Dict, Any, Tuple
import settings_manager
from app.config import settings, trading_config
from app.database.models import (
    SignalPayload,
    AgentDecisionOutput,
    RiskCheckResult,
    AgentOperationalCriticality,
    AgentHealthStatus,
    SystemDecisionState
)

class HeadDeskManagerAgent:
    name: str = "Head Desk Manager"
    criticality: str = AgentOperationalCriticality.SAFETY_CRITICAL

    # Canonical 6-Agent Quantitative Weights (Navigator removed, proportional renormalization)
    WEIGHTS = {
        "Technical Analyst Agent": 4 / 17,
        "Fundamental & Sentiment Agent": 3 / 17,
        "Liquidity & SMC Agent": 3 / 17,
        "Trade Quality Agent": 3 / 17,
        "Risk Management Agent": 4 / 17,
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
        Arbitrates final decision using weighted scoring, Agent Criticality hierarchy,
        and non-negotiable Safety Veto rules:
        - Returns (decision_status, decision_score, final_explanation)
        - Decision statuses: APPROVED, BLOCKED, DEGRADED_NO_TRADE, DATA_UNAVAILABLE
        """
        t_start = time.time()
        total_score = 0.0
        total_weight = 0.0
        veto_triggered = False
        veto_reasons = []
        degraded_reasons = []
        data_unavailable_reasons = []

        # 1. Criticality and Degraded-Mode Safety Inspection
        for dec in agent_decisions:
            w = self.WEIGHTS.get(dec.agent_name, 0.10)
            total_score += dec.score * w
            total_weight += w
            
            crit = getattr(dec, "operational_criticality", None)
            health = getattr(dec, "health_status", AgentHealthStatus.HEALTHY)
            
            # Check for Safety-Critical failures
            if crit == AgentOperationalCriticality.SAFETY_CRITICAL:
                if dec.decision == "VETO":
                    veto_triggered = True
                    veto_reasons.append(f"[{dec.agent_name} SAFETY VETO] {dec.reasoning_summary}")
                elif health in (AgentHealthStatus.ERROR, AgentHealthStatus.TIMEOUT, AgentHealthStatus.UNAVAILABLE):
                    veto_triggered = True
                    veto_reasons.append(f"[{dec.agent_name} SAFETY OFFLINE] Status: {health}, Error: {dec.error or dec.reasoning_summary}")
                elif health == AgentHealthStatus.STALE_DATA:
                    veto_triggered = True
                    data_unavailable_reasons.append(f"[{dec.agent_name} STALE DATA] Upstream feed stale: {dec.reasoning_summary}")
            
            # Check for Decision-Critical failures
            elif crit == AgentOperationalCriticality.DECISION_CRITICAL:
                if health in (AgentHealthStatus.ERROR, AgentHealthStatus.TIMEOUT, AgentHealthStatus.UNAVAILABLE):
                    degraded_reasons.append(f"[{dec.agent_name} OFFLINE] Critical agent offline ({health}): {dec.error or dec.reasoning_summary}")
                elif health == AgentHealthStatus.STALE_DATA:
                    degraded_reasons.append(f"[{dec.agent_name} STALE DATA] Upstream data expired: {dec.reasoning_summary}")
                elif dec.decision == "VETO":
                    veto_triggered = True
                    veto_reasons.append(f"[{dec.agent_name} VETO] {dec.reasoning_summary}")

        if not risk_check.passed:
            veto_triggered = True
            veto_reasons.append(f"[Risk Management Veto] {risk_check.veto_reason}")

        if guardian_veto:
            veto_triggered = True
            veto_reasons.append(f"[No-Trade Guardian] {guardian_reason}")

        final_score = round(total_score / (total_weight + 1e-6), 1)

        # 2. Safety Rule A: Data Unavailable Gate
        if data_unavailable_reasons:
            decision_status = "DATA_UNAVAILABLE"
            final_explanation = (
                f"[DECISION: DATA_UNAVAILABLE] ⚠️ Upstream Market Intelligence Stale/Offline.\n"
                f"• Aggregate Score: {final_score}/100\n"
                f"• Feed Diagnostics:\n  - " + "\n  - ".join(data_unavailable_reasons)
            )
            return decision_status, final_score, final_explanation

        # 3. Safety Rule B: Degraded Mode Gate (Decision-critical agent offline)
        if degraded_reasons:
            decision_status = "DEGRADED_NO_TRADE"
            final_explanation = (
                f"[DECISION: DEGRADED_NO_TRADE] ⚠️ System Operating in Degraded Mode — Trading Halted.\n"
                f"• Aggregate Score: {final_score}/100\n"
                f"• Unhealthy Critical Subsystems:\n  - " + "\n  - ".join(degraded_reasons) + "\n"
                f"• Safety Policy: Autonomous orders blocked until all critical intelligence agents recover."
            )
            return decision_status, final_score, final_explanation

        # 4. Safety Rule C: Hard Veto overrides all positive votes
        if veto_triggered:
            decision_status = "BLOCKED"
            final_explanation = (
                f"[DECISION: BLOCKED] 🚫 Trade Execution Halted by Non-Negotiable Safety Gate.\n"
                f"• Decision Confidence Score: {final_score}/100\n"
                f"• Critical Veto Reasons:\n  - " + "\n  - ".join(veto_reasons)
            )
            return decision_status, final_score, final_explanation

        # 5. Dynamic Multi-Agent Consensus Evaluation
        cur_settings = settings_manager.load_settings()
        min_confidence = float(cur_settings.get("min_confidence_threshold", getattr(settings, "MIN_AGENT_CONFIDENCE", 65.0)))
        min_agents_required = int(cur_settings.get("min_consensus_agents", getattr(settings, "MIN_CONSENSUS_AGENTS", 4)))

        agreeing_agents = [
            d for d in agent_decisions 
            if (d.decision == "PASS" or d.score >= min_confidence)
            and d.decision != "FAIL"
            and d.decision != "VETO"
        ]
        
        # General's vote counts as the 6th arbiter if aggregate score >= threshold
        general_agrees = (final_score >= min_confidence)
        total_agreeing = len(agreeing_agents) + (1 if general_agrees else 0)

        vol = getattr(signal, "volume", 0.01) or 0.01
        lot_str = f"{vol:.2f} Lots"
        sym_str = getattr(signal, "symbol", "XAUUSD") or "XAUUSD"

        if total_agreeing >= min_agents_required and final_score >= min_confidence and risk_check.passed:
            decision_status = "APPROVED"
            final_explanation = (
                f"[DECISION: APPROVED — HIGH CONVICTION] [CONSENSUS CLEARANCE GRANTED]\n"
                f"• Multi-Agent Consensus: {total_agreeing}/6 Agents in Full Agreement (>= {min_agents_required} Required)\n"
                f"• Aggregate Decision Confidence Score: {final_score}% (Threshold >= {int(min_confidence)}% Met)\n"
                f"• Risk-to-Reward: 1:{risk_check.rr_ratio:.2f} (>= 1:2.0 Verified) | Protected SL: ${signal.stop_loss:.2f} | TP: ${signal.take_profit:.2f}\n"
                f"• {lot_str} on {sym_str} approved for autonomous execution."
            )
        else:
            decision_status = f"BLOCKED ({total_agreeing}/6 Consensus)"
            final_explanation = (
                f"[DECISION: BLOCKED — INSUFFICIENT CONSENSUS] [EXECUTION HALTED]\n"
                f"• Multi-Agent Agreement: {total_agreeing}/6 Agents Agreed (Requires at least {min_agents_required}/6 with score >= {int(min_confidence)}%)\n"
                f"• Aggregate Decision Score: {final_score}%\n"
                f"• Capital preserved. Trade held until at least {min_agents_required} quantitative agents confirm setup alignment."
            )

        return decision_status, final_score, final_explanation

head_desk_agent = HeadDeskManagerAgent()


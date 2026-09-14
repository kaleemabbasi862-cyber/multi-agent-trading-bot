import uuid
import datetime
import time
from typing import Dict, Any, Optional
from app.config import settings, trading_config
from app.database.models import (
    SignalPayload,
    ConsensusResult,
    AgentDecisionOutput,
    RiskCheckResult,
    AgentOperationalCriticality,
    AgentHealthStatus,
    SystemDecisionState
)
from app.database.db import db
import ctrader_cloud_gateway

from app.agents.technical_agent import technical_agent
from app.agents.fundamental_agent import fundamental_agent
from app.agents.risk_agent import risk_agent
from app.agents.liquidity_agent import liquidity_agent
from app.agents.quality_agent import quality_agent
from app.agents.head_desk_agent import head_desk_agent
from app.agents.guardian import guardian
from app.engine.explainability_engine import explainability_engine

_PROCESSED_SIGNAL_IDS = set()

class MultiAgentConsensusEngine:
    """
    Orchestrates the 6-Agent Quantitative Decision Pipeline + No-Trade Guardian.
    Computes weighted multi-agent consensus, enforces safety gates, and synthesizes bilingual Decision DNA.
    """

    def process_signal(
        self,
        signal: SignalPayload,
        market_data: Dict[str, Any],
        macro_data: Dict[str, Any],
        account_status: Dict[str, Any],
        save_to_db: bool = True,
        pretrade_scan: Optional[Dict[str, Any]] = None
    ) -> ConsensusResult:
        if not signal.id:
            signal.id = f"SIG_{uuid.uuid4().hex[:8].upper()}"
            
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if not signal.timestamp:
            signal.timestamp = now_iso

        intent_id = f"INTENT_{uuid.uuid4().hex[:12].upper()}"
        critical_failures = []

        # 1. Run No-Trade Guardian (17 Defense-in-Depth Rules)
        is_guarded, guard_reason = guardian.check_guard_rules(
            signal, market_data, macro_data, account_status, _PROCESSED_SIGNAL_IDS
        )
        
        # 2. Run All 5 Analytical / Risk Agents (Fail-safe per agent with Health Contracts)
        try:
            tech_decision = technical_agent.evaluate(signal, market_data)
            if tech_decision.health_status != AgentHealthStatus.HEALTHY and tech_decision.decision != "PASS":
                critical_failures.append(f"Chart Sniper: {tech_decision.health_status}")
        except Exception as e:
            critical_failures.append(f"Chart Sniper: ERROR ({e})")
            tech_decision = AgentDecisionOutput(
                agent_name="Technical Analyst Agent",
                direction="NEUTRAL",
                score=0.0,
                decision="FAIL",
                reasoning_summary=f"Technical Agent Offline / Error: {e}",
                operational_criticality=AgentOperationalCriticality.DECISION_CRITICAL,
                health_status=AgentHealthStatus.ERROR,
                error=str(e),
                metrics={"error": str(e), "unavailable": True}
            )

        try:
            fund_decision = fundamental_agent.evaluate(signal, macro_data)
            if fund_decision.health_status != AgentHealthStatus.HEALTHY:
                critical_failures.append(f"News Radar: {fund_decision.health_status}")
        except Exception as e:
            critical_failures.append(f"News Radar: ERROR ({e})")
            fund_decision = AgentDecisionOutput(
                agent_name="Fundamental & Sentiment Agent",
                direction="NEUTRAL",
                score=0.0,
                decision="VETO",
                reasoning_summary=f"Fundamental Agent Offline / Error: {e}",
                operational_criticality=AgentOperationalCriticality.SAFETY_CRITICAL,
                health_status=AgentHealthStatus.ERROR,
                error=str(e),
                metrics={"error": str(e), "unavailable": True}
            )

        try:
            risk_decision, risk_check_res = risk_agent.evaluate(signal, account_status, market_data)
            if risk_decision.health_status != AgentHealthStatus.HEALTHY:
                critical_failures.append(f"Shield Guard: {risk_decision.health_status}")
        except Exception as e:
            critical_failures.append(f"Shield Guard: ERROR ({e})")
            risk_decision = AgentDecisionOutput(
                agent_name="Risk Management Agent",
                direction="NEUTRAL",
                score=0.0,
                decision="VETO",
                reasoning_summary=f"Risk Agent Failed to Evaluate: {e}",
                operational_criticality=AgentOperationalCriticality.SAFETY_CRITICAL,
                health_status=AgentHealthStatus.ERROR,
                error=str(e),
                metrics={"error": str(e), "unavailable": True}
            )
            risk_check_res = RiskCheckResult(
                passed=False,
                account_balance=float(account_status.get("balance", 0.0)),
                account_equity=float(account_status.get("equity", 0.0)),
                risk_amount=0.0,
                calculated_volume=0.01,
                sl_distance=0.0,
                tp_distance=0.0,
                rr_ratio=0.0,
                spread=float(market_data.get("spread", 0.35)),
                veto_reason=f"CRITICAL: Risk Agent error - fail closed: {e}"
            )

        try:
            liq_decision = liquidity_agent.evaluate(signal, market_data)
            if liq_decision.health_status != AgentHealthStatus.HEALTHY and liq_decision.decision != "PASS":
                critical_failures.append(f"SMC Hunter: {liq_decision.health_status}")
        except Exception as e:
            critical_failures.append(f"SMC Hunter: ERROR ({e})")
            liq_decision = AgentDecisionOutput(
                agent_name="Liquidity & SMC Agent",
                direction="NEUTRAL",
                score=0.0,
                decision="FAIL",
                reasoning_summary=f"Liquidity & SMC Agent Offline / Error: {e}",
                operational_criticality=AgentOperationalCriticality.DECISION_CRITICAL,
                health_status=AgentHealthStatus.ERROR,
                error=str(e),
                metrics={"error": str(e), "unavailable": True}
            )

        try:
            acc_id = ctrader_cloud_gateway.get_active_account_id()
            hist_stats = db.get_performance_stats(broker_account_id=acc_id) if acc_id else {"closed_trades": 0, "win_rate": 0.0, "net_pnl": 0.0, "gross_profit": 0.0, "gross_loss": 0.0, "profit_factor": 1.0, "avg_trade_pnl": 0.0}
            quality_decision = quality_agent.evaluate(signal, hist_stats, market_data)
        except Exception as e:
            critical_failures.append(f"Quant Brain: ERROR ({e})")
            quality_decision = AgentDecisionOutput(
                agent_name="Trade Quality Agent",
                direction="NEUTRAL",
                score=0.0,
                decision="FAIL",
                reasoning_summary=f"Quality Agent Offline / Error: {e}",
                operational_criticality=AgentOperationalCriticality.DECISION_CRITICAL,
                health_status=AgentHealthStatus.ERROR,
                error=str(e),
                metrics={"error": str(e), "unavailable": True}
            )

        all_agent_decisions = [
            tech_decision,
            fund_decision,
            liq_decision,
            quality_decision,
            risk_decision
        ]

        # 3. Arbitrate Final Decision via Head Desk Manager (The General, sixth participant)
        status, score, explanation = head_desk_agent.arbitrate(
            signal=signal,
            agent_decisions=all_agent_decisions,
            risk_check=risk_check_res,
            guardian_veto=is_guarded,
            guardian_reason=guard_reason
        )

        # Determine explicit system decision state
        if status == "APPROVED":
            system_state = SystemDecisionState.APPROVED
        elif "DATA_UNAVAILABLE" in status:
            system_state = SystemDecisionState.DATA_UNAVAILABLE
        elif "DEGRADED" in status:
            system_state = SystemDecisionState.DEGRADED_NO_TRADE
        elif "BLOCKED" in status:
            system_state = SystemDecisionState.BLOCKED
        else:
            system_state = SystemDecisionState.NO_TRADE

        # 4. Generate Bilingual Explainability Narrative
        explain_data = explainability_engine.generate_explanation(
            signal=signal,
            status=status,
            score=score,
            agent_decisions=all_agent_decisions,
            risk_check=risk_check_res,
            is_guarded=is_guarded,
            guard_reason=guard_reason,
            macro_data=macro_data
        )

        combined_explanation = f"{explanation}\n\n[URDU EXPLANATION / اردو خلاصہ]:\n{explain_data['summary_ur']}"

        if save_to_db:
            _PROCESSED_SIGNAL_IDS.add(signal.id)

            # 5. Generate Immutable Decision DNA Snapshot
            decision_dna_snapshot = {
                "signal_id": signal.id,
                "execution_intent_id": intent_id,
                "config_version": trading_config.version,
                "system_state": system_state,
                "created_at": now_iso,
                "signal": signal.dict(),
                "status": status,
                "decision_score": score,
                "explanation": combined_explanation,
                "explainability": explain_data,
                "market_snapshot": market_data,
                "macro_snapshot": macro_data,
                "account_snapshot": account_status,
                "agent_evaluations": [d.dict() for d in all_agent_decisions],
                "risk_check": risk_check_res.dict(),
                "guardian": {
                    "blocked": is_guarded,
                    "reason": guard_reason
                },
                "critical_agent_failures": critical_failures
            }

            # Persist Pre-Trade Quality Score telemetry (additive, backward-compatible)
            if pretrade_scan and isinstance(pretrade_scan, dict):
                qs = pretrade_scan.get("quality_score", {})
                if qs and isinstance(qs, dict):
                    decision_dna_snapshot["quality_telemetry"] = {
                        "score": qs.get("score"),
                        "threshold": qs.get("threshold"),
                        "passed": qs.get("passed"),
                        "verdict": qs.get("verdict"),
                        "breakdown": qs.get("breakdown"),
                        "setup_type": pretrade_scan.get("setup", {}).get("setup_type"),
                        "trade_allowed": pretrade_scan.get("trade_allowed"),
                        "decision_reason": pretrade_scan.get("decision_reason"),
                        "adx": pretrade_scan.get("indicators", {}).get("adx", {}).get("adx") if isinstance(pretrade_scan.get("indicators", {}).get("adx"), dict) else pretrade_scan.get("indicators", {}).get("adx"),
                        "rsi": pretrade_scan.get("indicators", {}).get("rsi"),
                        "spread_pips": pretrade_scan.get("spread_pips"),
                        "smc_structure": pretrade_scan.get("smc", {}).get("structure"),
                        "mtf_consensus": pretrade_scan.get("mtf", {}).get("consensus_trend"),
                        "dealing_zone": pretrade_scan.get("smc", {}).get("dealing_range", {}).get("zone"),
                    "reached_consensus": True,
                    "consensus_status": status,
                    "execution_dispatched": False
                    }

            # 6. Persist to SQLite Database
            db.save_signal({
                "id": signal.id,
                "timestamp": signal.timestamp,
                "symbol": signal.symbol,
                "direction": signal.action,
                "source": signal.source,
                "entry_price": signal.entry_price,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "rr_ratio": risk_check_res.rr_ratio,
                "timeframe": signal.timeframe,
                "status": status,
                "decision_score": score,
                "rejection_reason": guard_reason if is_guarded else (risk_check_res.veto_reason if not risk_check_res.passed else None),
                "execution_intent_id": intent_id
            })

            db.save_agent_decisions(signal.id, [d.dict() for d in all_agent_decisions])
            db.save_risk_check({
                "signal_id": signal.id,
                "account_balance": risk_check_res.account_balance,
                "account_equity": risk_check_res.account_equity,
                "risk_amount": risk_check_res.risk_amount,
                "calculated_volume": risk_check_res.calculated_volume,
                "sl_distance": risk_check_res.sl_distance,
                "tp_distance": risk_check_res.tp_distance,
                "rr_ratio": risk_check_res.rr_ratio,
                "spread": risk_check_res.spread,
                "passed": risk_check_res.passed,
                "veto_reason": risk_check_res.veto_reason,
                "initial_r": risk_check_res.initial_r
            })

            db.save_decision_dna(signal.id, decision_dna_snapshot)

            db.log_audit(
                event_type="SIGNAL_PROCESSED",
                actor="MultiAgentConsensusEngine",
                details=f"Signal {signal.id} ({signal.symbol} {signal.action} @ {signal.entry_price}) -> {status} (Score: {score}%) [State: {system_state}]"
            )

        return ConsensusResult(
            signal_id=signal.id,
            symbol=signal.symbol,
            direction=signal.action,
            decision_status=status,
            decision_score=score,
            agent_decisions=all_agent_decisions,
            risk_check=risk_check_res,
            full_analysis=combined_explanation,
            decision_dna_id=signal.id,
            execution_intent_id=intent_id,
            system_state=system_state,
            critical_agent_failures=critical_failures
        )

consensus_engine = MultiAgentConsensusEngine()



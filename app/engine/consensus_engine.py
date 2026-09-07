import uuid
import datetime
import time
from typing import Dict, Any, Optional
from app.config import settings
from app.database.models import SignalPayload, ConsensusResult
from app.database.db import db

from app.agents.technical_agent import technical_agent
from app.agents.fundamental_agent import fundamental_agent
from app.agents.risk_agent import risk_agent
from app.agents.regime_agent import regime_agent
from app.agents.liquidity_agent import liquidity_agent
from app.agents.quality_agent import quality_agent
from app.agents.head_desk_agent import head_desk_agent
from app.agents.guardian import guardian

_PROCESSED_SIGNAL_IDS = set()

class MultiAgentConsensusEngine:
    """
    Orchestrates the 7-Agent Quantitative Decision Pipeline + No-Trade Guardian.
    """

    def process_signal(
        self,
        signal: SignalPayload,
        market_data: Dict[str, Any],
        macro_data: Dict[str, Any],
        account_status: Dict[str, Any],
        save_to_db: bool = True
    ) -> ConsensusResult:
        if not signal.id:
            signal.id = f"SIG_{uuid.uuid4().hex[:8].upper()}"
            
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if not signal.timestamp:
            signal.timestamp = now_iso

        # 1. Run No-Trade Guardian (16 Defense-in-Depth Rules)
        is_guarded, guard_reason = guardian.check_guard_rules(
            signal, market_data, macro_data, account_status, _PROCESSED_SIGNAL_IDS
        )
        
        # 2. Run All 6 Analytical / Risk Agents
        tech_decision = technical_agent.evaluate(signal, market_data)
        fund_decision = fundamental_agent.evaluate(signal, macro_data)
        risk_decision, risk_check_res = risk_agent.evaluate(signal, account_status, market_data)
        regime_decision = regime_agent.evaluate(signal, market_data)
        liq_decision = liquidity_agent.evaluate(signal, market_data)
        
        hist_stats = db.get_performance_stats()
        quality_decision = quality_agent.evaluate(signal, hist_stats, market_data)

        all_agent_decisions = [
            tech_decision,
            fund_decision,
            regime_decision,
            liq_decision,
            quality_decision,
            risk_decision
        ]

        # 3. Arbitrate Final Decision via Head Desk Manager (Agent 7)
        status, score, explanation = head_desk_agent.arbitrate(
            signal=signal,
            agent_decisions=all_agent_decisions,
            risk_check=risk_check_res,
            guardian_veto=is_guarded,
            guardian_reason=guard_reason
        )

        if save_to_db:
            _PROCESSED_SIGNAL_IDS.add(signal.id)

            # 4. Generate Immutable Decision DNA Snapshot
            decision_dna_snapshot = {
                "signal_id": signal.id,
                "created_at": now_iso,
                "signal": signal.dict(),
                "status": status,
                "decision_score": score,
                "explanation": explanation,
                "market_snapshot": market_data,
                "macro_snapshot": macro_data,
                "account_snapshot": account_status,
                "agent_evaluations": [d.dict() for d in all_agent_decisions],
                "risk_check": risk_check_res.dict(),
                "guardian": {
                    "blocked": is_guarded,
                    "reason": guard_reason
                }
            }

            # 5. Persist to SQLite Database
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
                "rejection_reason": guard_reason if is_guarded else (risk_check_res.veto_reason if not risk_check_res.passed else None)
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
                "veto_reason": risk_check_res.veto_reason
            })

            db.save_decision_dna(signal.id, decision_dna_snapshot)

            db.log_audit(
                event_type="SIGNAL_PROCESSED",
                actor="MultiAgentConsensusEngine",
                details=f"Signal {signal.id} ({signal.symbol} {signal.action} @ {signal.entry_price}) -> {status} (Score: {score}%)"
            )

        return ConsensusResult(
            signal_id=signal.id,
            symbol=signal.symbol,
            direction=signal.action,
            decision_status=status,
            decision_score=score,
            agent_decisions=all_agent_decisions,
            risk_check=risk_check_res,
            full_analysis=explanation,
            decision_dna_id=signal.id
        )

consensus_engine = MultiAgentConsensusEngine()

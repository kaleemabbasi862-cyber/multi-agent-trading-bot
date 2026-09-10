import time
import datetime
import math
from typing import Dict, Any, Tuple
from app.config import settings
from app.database.models import (
    SignalPayload,
    AgentDecisionOutput,
    RiskCheckResult,
    AgentOperationalCriticality,
    AgentHealthStatus,
    DataProvenance
)
import settings_manager

class RiskManagementAgent:
    name: str = "Risk Management Agent"
    weight: float = 0.20
    has_veto_power: bool = True
    criticality: str = AgentOperationalCriticality.SAFETY_CRITICAL

    def evaluate(self, signal: SignalPayload, account_status: Dict[str, Any], market_feed_data: Dict[str, Any]) -> Tuple[AgentDecisionOutput, RiskCheckResult]:
        t_start = time.time()
        start_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        p = float(signal.entry_price or 0.0)
        sl = float(signal.stop_loss or 0.0)
        tp = float(signal.take_profit or 0.0)
        act = signal.action.upper()
        sym = (signal.symbol or "XAUUSD").upper().replace("M", "").replace(".PRO", "").replace("_I", "")
        
        bal = float(account_status.get("balance", 1000.0))
        eq = float(account_status.get("equity", bal))
        f_marg = float(account_status.get("free_margin", eq))
        open_pos = account_status.get("open_positions", [])
        daily_loss = float(account_status.get("daily_loss", 0.0))
        consecutive_losses = int(account_status.get("consecutive_losses", 0))
        circuit_breaker_active = bool(account_status.get("circuit_breaker_active", False))
        
        spread = float(market_feed_data.get("spread", 0.35))
        pip_size = float(market_feed_data.get("pip_size", 0.01))
        
        reasons = []
        veto_reason = None
        passed = True
        score = 95.0
        
        # 1. Whitelist Check
        if not settings_manager.is_pair_whitelisted(sym):
            passed = False
            veto_reason = f"Instrument ({sym}) is not in active whitelist."
            reasons.append(veto_reason)
            score = 0.0
            
        # 2. Max Open Positions Check
        elif len(open_pos) >= settings.MAX_OPEN_POSITIONS:
            passed = False
            veto_reason = f"Max open positions hard cap ({settings.MAX_OPEN_POSITIONS}) reached. Currently active: {len(open_pos)}"
            reasons.append(veto_reason)
            score = 0.0
            
        # 3. Circuit Breakers & Daily Loss Limit
        elif circuit_breaker_active or daily_loss <= -settings.DAILY_LOSS_LIMIT:
            passed = False
            veto_reason = f"Circuit Breaker ACTIVE: Daily loss limit hit (${abs(daily_loss):.2f} / ${settings.DAILY_LOSS_LIMIT:.2f})"
            reasons.append(veto_reason)
            score = 0.0
            
        # 4. Consecutive Losses Check
        elif consecutive_losses >= settings.MAX_CONSECUTIVE_LOSSES:
            passed = False
            veto_reason = f"Circuit Breaker ACTIVE: Max consecutive losses ({consecutive_losses}/{settings.MAX_CONSECUTIVE_LOSSES}) reached."
            reasons.append(veto_reason)
            score = 0.0
            
        # 5. Mandatory SL / TP Pre-Validation
        elif sl <= 0 or tp <= 0:
            passed = False
            veto_reason = f"Unprotected order rejected: SL (${sl}) or TP (${tp}) is not set."
            reasons.append(veto_reason)
            score = 0.0
            
        else:
            # 6. Directional Validation
            sl_distance = abs(p - sl)
            tp_distance = abs(tp - p)
            
            if act == "BUY" and sl >= p:
                passed = False
                veto_reason = f"Invalid BUY SL: SL (${sl:.2f}) must be strictly below Entry (${p:.2f})"
                reasons.append(veto_reason)
                score = 0.0
            elif act == "SELL" and sl <= p:
                passed = False
                veto_reason = f"Invalid SELL SL: SL (${sl:.2f}) must be strictly above Entry (${p:.2f})"
                reasons.append(veto_reason)
                score = 0.0
            elif act == "BUY" and tp <= p:
                passed = False
                veto_reason = f"Invalid BUY TP: TP (${tp:.2f}) must be strictly above Entry (${p:.2f})"
                reasons.append(veto_reason)
                score = 0.0
            elif act == "SELL" and tp >= p:
                passed = False
                veto_reason = f"Invalid SELL TP: TP (${tp:.2f}) must be strictly below Entry (${p:.2f})"
                reasons.append(veto_reason)
                score = 0.0
                
            # 7. Broker Minimum Stop Distance Check (>= 4.0x Spread & >= $2.50 breathing room on Gold)
            is_gold = "XAU" in sym or "GOLD" in sym
            min_safe_sl_distance = max(spread * settings.MIN_SL_SPREAD_MULTIPLIER, getattr(settings, "MIN_SL_BUFFER_GOLD", 2.50) if is_gold else (pip_size * 40.0))
            if sl_distance < min_safe_sl_distance:
                passed = False
                veto_reason = f"SL distance (${sl_distance:.2f}) too tight for broker spread. Must be >= ${min_safe_sl_distance:.2f} (Breathing room guard)"
                reasons.append(veto_reason)
                score = 10.0
                
            # 8. Minimum Risk-to-Reward Ratio (>= 2.0)
            rr_ratio = round(tp_distance / (sl_distance + 1e-6), 2)
            if rr_ratio < settings.MIN_RR_RATIO:
                passed = False
                veto_reason = f"Insufficient Risk:Reward ratio (1:{rr_ratio:.2f}). Must be >= 1:{settings.MIN_RR_RATIO:.1f}"
                reasons.append(veto_reason)
                score = 25.0
            else:
                reasons.append(f"Risk:Reward 1:{rr_ratio:.2f} satisfies >= 1:{settings.MIN_RR_RATIO:.1f} criterion")

        # 9. Monetary Risk & Canonical 1R Calculation (1 Lot of Gold = 100 oz)
        sl_dist = round(abs(p - sl), 2)
        tp_dist = round(abs(tp - p), 2)
        rr = round(tp_dist / (sl_dist + 1e-6), 2)
        monetary_risk = round(sl_dist * (settings.DEFAULT_LOT_SIZE * 100), 2)
        max_allowed_risk_dollars = round((settings.MAX_ACCOUNT_RISK_PERCENT / 100.0) * eq, 2)
        
        if max_allowed_risk_dollars < 0.40:
            max_allowed_risk_dollars = 0.60
            
        if passed:
            reasons.append(f"Calculated monetary risk: ${monetary_risk:.2f} on {settings.DEFAULT_LOT_SIZE} micro-lot")
            reasons.append(f"Canonical Initial 1R established: ${sl_dist:.2f}")
            decision = "PASS"
        else:
            decision = "VETO"
            
        summary = f"Risk Score: {score:.1f}/100. " + "; ".join(reasons)
        t_end = time.time()
        end_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        agent_out = AgentDecisionOutput(
            agent_name=self.name,
            direction=act if passed else "NEUTRAL",
            score=score,
            decision=decision,
            reasoning_summary=summary,
            operational_criticality=self.criticality,
            health_status=AgentHealthStatus.HEALTHY if passed else (AgentHealthStatus.INVALID_INPUT if sl <= 0 else AgentHealthStatus.HEALTHY),
            execution_started_at=start_iso,
            execution_completed_at=end_iso,
            execution_latency_ms=round((t_end - t_start) * 1000, 2),
            data_source="cTrader Account & Feed Telemetry",
            confidence=1.0 if passed else 0.0,
            decision_id=signal.id,
            metrics={
                "account_balance": bal,
                "account_equity": eq,
                "monetary_risk": monetary_risk,
                "max_allowed_risk_dollars": max_allowed_risk_dollars,
                "sl_distance": sl_dist,
                "tp_distance": tp_dist,
                "initial_r": sl_dist,
                "rr_ratio": rr,
                "spread": spread,
                "passed": passed,
                "has_veto_power": True
            }
        )
        
        risk_check_res = RiskCheckResult(
            passed=passed,
            account_balance=bal,
            account_equity=eq,
            risk_amount=monetary_risk,
            calculated_volume=settings.DEFAULT_LOT_SIZE,
            sl_distance=sl_dist,
            tp_distance=tp_dist,
            rr_ratio=rr,
            spread=spread,
            veto_reason=veto_reason,
            initial_r=sl_dist,
            data_provenance=DataProvenance.BROKER_DEMO
        )
        
        return agent_out, risk_check_res

risk_agent = RiskManagementAgent()

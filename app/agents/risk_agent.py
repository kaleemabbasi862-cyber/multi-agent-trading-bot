import math
from typing import Dict, Any, Tuple
from app.config import settings
from app.database.models import SignalPayload, AgentDecisionOutput, RiskCheckResult

class RiskManagementAgent:
    name: str = "Risk Management Agent"
    weight: float = 0.20
    has_veto_power: bool = True

    def evaluate(self, signal: SignalPayload, account_status: Dict[str, Any], market_feed_data: Dict[str, Any]) -> Tuple[AgentDecisionOutput, RiskCheckResult]:
        p = signal.entry_price
        sl = signal.stop_loss
        tp = signal.take_profit
        act = signal.action.upper()
        sym = signal.symbol.upper().replace("M", "").replace(".PRO", "").replace("_I", "")
        
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
        
        # 1. Whitelist Check (Strict Gold XAUUSD)
        if "XAU" not in sym and "GOLD" not in sym:
            passed = False
            veto_reason = f"Non-Gold instrument ({sym}) strictly rejected per Gold Directive."
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
                
            # 7. Broker Minimum Stop Distance Check (>= 3.0x Spread)
            min_safe_sl_distance = max(spread * settings.MIN_SL_SPREAD_MULTIPLIER, pip_size * 40.0) # $0.40 min on Gold
            if sl_distance < min_safe_sl_distance:
                passed = False
                veto_reason = f"SL distance (${sl_distance:.2f}) too tight for broker spread. Must be >= ${min_safe_sl_distance:.2f} (3.0x Spread)"
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

        # 9. Monetary Risk Calculation (1 Lot of Gold = 100 oz)
        # For 0.01 lot, $1 move in Gold = $1.00 PnL
        sl_dist = abs(p - sl)
        tp_dist = abs(tp - p)
        rr = round(tp_dist / (sl_dist + 1e-6), 2)
        monetary_risk = round(sl_dist * (settings.DEFAULT_LOT_SIZE * 100), 2)
        max_allowed_risk_dollars = round((settings.MAX_ACCOUNT_RISK_PERCENT / 100.0) * eq, 2)
        
        # If micro-account ($38 balance), max allowed risk is at least $0.40 - $1.00
        if max_allowed_risk_dollars < 0.40:
            max_allowed_risk_dollars = 0.60
            
        if passed:
            reasons.append(f"Calculated monetary risk: ${monetary_risk:.2f} on {settings.DEFAULT_LOT_SIZE} micro-lot")
            reasons.append(f"Guaranteed SL pre-validated (Distance: ${sl_dist:.2f} >= 3x Spread)")
            decision = "PASS"
        else:
            decision = "VETO"
            
        summary = f"Risk Score: {score:.1f}/100. " + "; ".join(reasons)
        
        agent_out = AgentDecisionOutput(
            agent_name=self.name,
            direction=act if passed else "NEUTRAL",
            score=score,
            decision=decision,
            reasoning_summary=summary,
            metrics={
                "account_balance": bal,
                "account_equity": eq,
                "monetary_risk": monetary_risk,
                "max_allowed_risk_dollars": max_allowed_risk_dollars,
                "sl_distance": sl_dist,
                "tp_distance": tp_dist,
                "rr_ratio": rr,
                "spread": spread,
                "passed": passed
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
            veto_reason=veto_reason
        )
        
        return agent_out, risk_check_res

risk_agent = RiskManagementAgent()

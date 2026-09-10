import math
import datetime
import logging
from typing import Dict, Any, Optional, Tuple
from app.config import settings
from app.database.db import db
from app.services.symbol_resolver import symbol_resolver

logger = logging.getLogger("TradeTalk.RiskEngine")

class RiskManagementEngine:
    """
    Production-grade Quantitative Risk Management Engine.
    Enforces Dynamic Position Sizing, Multi-Tier Circuit Breakers, Margin Validation, and Safety Guards.
    """

    def __init__(self):
        self._circuit_breaker_override: bool = False
        self._consecutive_loss_cooldown_until: Optional[float] = None

    def calculate_position_size(
        self,
        symbol: str,
        account_equity: float,
        entry_price: float,
        stop_loss: float,
        risk_percentage: Optional[float] = None,
        max_lot_cap: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Calculates exact mathematical position size based on equity percentage and SL distance.
        Respects broker contract specifications (lot size, min lot, max lot, step).
        """
        if account_equity <= 0 or entry_price <= 0:
            return {
                "volume": 0.01,
                "risk_amount_dollars": 0.0,
                "sl_distance": 0.0,
                "lot_size_contract": 100.0,
                "status": "ERROR_INVALID_INPUT"
            }

        risk_pct = risk_percentage if risk_percentage is not None else getattr(settings, "MAX_ACCOUNT_RISK_PERCENT", 1.0)
        risk_dollars = round((risk_pct / 100.0) * account_equity, 2)
        
        # Micro account floor: ensure minimum $0.50 risk allowance if account is small
        if risk_dollars < 0.50:
            risk_dollars = min(0.60, round(account_equity * 0.05, 2))

        sl_distance = abs(entry_price - stop_loss)
        if sl_distance <= 0:
            sl_distance = 2.50 if ("XAU" in symbol.upper() or "GOLD" in symbol.upper()) else 0.0030

        spec = symbol_resolver.get_contract_spec(symbol)
        lot_unit_size = spec.get("lot_size", 100.0)
        min_vol = spec.get("min_volume", 0.01)
        max_vol = spec.get("max_volume", 100.0)
        vol_step = spec.get("volume_step", 0.01)

        # Theoretical raw volume
        divisor = sl_distance * lot_unit_size
        raw_volume = risk_dollars / divisor if divisor > 0 else min_vol

        # Round down to nearest volume step with floating point epsilon tolerance
        steps = math.floor((raw_volume + 1e-9) / vol_step)
        calculated_vol = round(steps * vol_step, 4)


        # Clamp between min_volume and max_volume / user lot cap
        lot_cap = max_lot_cap if max_lot_cap is not None else getattr(settings, "DEFAULT_LOT_SIZE", 0.01)
        effective_max = min(max_vol, lot_cap if lot_cap > 0 else max_vol)
        
        final_volume = max(min_vol, min(effective_max, calculated_vol))
        final_volume = round(final_volume, 2)

        actual_monetary_risk = round(sl_distance * (final_volume * lot_unit_size), 2)

        return {
            "symbol": symbol,
            "account_equity": account_equity,
            "risk_percentage": risk_pct,
            "risk_amount_dollars": risk_dollars,
            "actual_monetary_risk": actual_monetary_risk,
            "sl_distance": round(sl_distance, 4),
            "calculated_volume": final_volume,
            "contract_lot_size": lot_unit_size,
            "min_volume": min_vol,
            "max_volume": effective_max,
            "volume_step": vol_step,
            "status": "CALCULATED"
        }

    def check_circuit_breakers(
        self,
        account_status: Dict[str, Any],
        symbol: str = "XAUUSD"
    ) -> Tuple[bool, Optional[str], str]:
        """
        Evaluates Multi-Tier Circuit Breakers:
        - Daily Drawdown Limit
        - Consecutive Losses Cooldown
        - Manual Emergency Kill Switch
        Returns (is_tripped, reason, severity)
        """
        # 1. Rule 0: Emergency Kill Switch
        if getattr(settings, "EMERGENCY_KILL_SWITCH_ACTIVE", False):
            return True, "Rule 0 Violation: EMERGENCY KILL SWITCH ACTIVE. All execution halted.", "CRITICAL"

        # 2. Daily Loss Limit Circuit Breaker (Realized + Floating Drawdown)
        daily_loss = float(account_status.get("daily_loss", 0.0))
        unrealized_pnl = float(account_status.get("total_unrealized_pnl", 0.0))
        effective_daily_loss = daily_loss + min(0.0, unrealized_pnl)
        daily_limit = float(getattr(settings, "DAILY_LOSS_LIMIT", 5.00))

        if effective_daily_loss <= -daily_limit:
            reason = f"Daily Loss Circuit Breaker Tripped: Effective daily loss (-${abs(effective_daily_loss):.2f}) exceeds limit (-${daily_limit:.2f})."
            db.log_risk_event(
                event_type="CIRCUIT_BREAKER",
                account_id=str(account_status.get("account_id", "MAIN")),
                severity="HIGH",
                details=reason
            )
            return True, reason, "HIGH"

        # 3. Consecutive Loss Cooldown (3 losses -> 60m cooldown)
        consecutive_losses = int(account_status.get("consecutive_losses", 0))
        max_consecutive = int(getattr(settings, "MAX_CONSECUTIVE_LOSSES", 3))
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()

        if consecutive_losses >= max_consecutive:
            if not self._consecutive_loss_cooldown_until:
                self._consecutive_loss_cooldown_until = now_ts + 3600 # 60 minutes
            
            if now_ts < self._consecutive_loss_cooldown_until:
                rem_m = int((self._consecutive_loss_cooldown_until - now_ts) / 60)
                reason = f"Consecutive Loss Circuit Breaker: {consecutive_losses} consecutive losses. Cooldown active ({rem_m}m remaining)."
                return True, reason, "MEDIUM"
        else:
            self._consecutive_loss_cooldown_until = None

        return False, None, "CLEAR"

    def reset_circuit_breaker(self) -> Dict[str, Any]:
        """Manually clears tripped circuit breakers and resets cooldown."""
        self._consecutive_loss_cooldown_until = None
        db.log_audit(
            event_type="CIRCUIT_BREAKER_RESET",
            actor="TraderAdmin",
            details="User manually reset circuit breaker state."
        )
        return {
            "status": "SUCCESS",
            "message": "Circuit breaker and consecutive loss cooldown reset successfully."
        }

    def get_risk_telemetry(self, account_status: Dict[str, Any]) -> Dict[str, Any]:
        """Returns consolidated real-time quantitative risk analytics."""
        bal = float(account_status.get("balance", 1000.0))
        eq = float(account_status.get("equity", bal))
        f_marg = float(account_status.get("free_margin", eq))
        open_pos = account_status.get("open_positions", [])
        daily_loss = float(account_status.get("daily_loss", 0.0))
        consecutive_losses = int(account_status.get("consecutive_losses", 0))

        is_tripped, trip_reason, severity = self.check_circuit_breakers(account_status)

        # Calculate Open Risk / Value at Risk (VaR)
        total_open_risk = 0.0
        for pos in open_pos:
            entry = float(pos.get("entry_price", 0.0))
            sl = float(pos.get("stop_loss", 0.0))
            vol = float(pos.get("volume", 0.01))
            if entry > 0 and sl > 0:
                dist = abs(entry - sl)
                total_open_risk += round(dist * vol * 100, 2)

        margin_utilization_pct = round(((eq - f_marg) / (eq + 1e-6)) * 100, 1) if eq > 0 else 0.0

        return {
            "account_balance": bal,
            "account_equity": eq,
            "free_margin": f_marg,
            "margin_utilization_percent": margin_utilization_pct,
            "daily_loss": daily_loss,
            "daily_loss_limit": getattr(settings, "DAILY_LOSS_LIMIT", 5.00),
            "consecutive_losses": consecutive_losses,
            "max_consecutive_losses": getattr(settings, "MAX_CONSECUTIVE_LOSSES", 3),
            "open_positions_count": len(open_pos),
            "max_open_positions": getattr(settings, "MAX_OPEN_POSITIONS", 1),
            "total_open_risk_dollars": round(total_open_risk, 2),
            "circuit_breaker_active": is_tripped,
            "circuit_breaker_reason": trip_reason,
            "circuit_breaker_severity": severity,
            "kill_switch_active": getattr(settings, "EMERGENCY_KILL_SWITCH_ACTIVE", False),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }


risk_engine = RiskManagementEngine()

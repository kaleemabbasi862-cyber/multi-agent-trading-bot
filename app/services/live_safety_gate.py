import logging
from typing import Dict, Any, Tuple, Optional
from app.services.credential_store import credential_store
from app.services.economic_calendar import economic_calendar_service
from app.services.risk_engine import risk_engine
from app.services.symbol_resolver import symbol_resolver
from app.services.market_data_integrity_monitor import market_data_integrity_monitor
from app.services.volatility_engine import volatility_engine
from app.services.position_manager_v3 import position_manager_v3
from app.services.ctrader_market_data import market_data_health_monitor
import ctrader_cloud_gateway

logger = logging.getLogger("TradeTalk.LiveSafetyGate")

class LiveSafetyGate:
    """
    Phase 10: Live Trading Safety System & Gatekeeper.
    Enforces multi-tier non-negotiable safety locks before allowing orders
    into cTrader Live / Demo accounts.
    """

    MAX_SPREAD_PIPS_MAP = {
        "XAUUSD": 4.5,
        "GOLD": 4.5,
        "EURUSD": 2.5,
        "GBPUSD": 3.0,
        "USDJPY": 2.5,
        "AUDUSD": 2.5
    }

    MAX_CONCURRENT_POSITIONS = 1

    @classmethod
    def evaluate_order_safety(
        cls,
        symbol: str,
        action: str,
        volume: float,
        entry_price: float,
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None,
        current_spread_pips: Optional[float] = None,
        ignore_news_lockout: bool = False,
        require_fresh_quotes: bool = False
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Runs comprehensive 8-layer safety evaluation on proposed trade order.
        Returns (is_approved, rejection_reason, telemetry_data).
        """
        sym = symbol.upper()
        act = action.upper()

        # 1. EMERGENCY KILL SWITCH CHECK
        if credential_store.is_kill_switch_active():
            reason = "VETO_EMERGENCY_KILL_SWITCH_ACTIVE: Global trading is locked by operator."
            logger.warning(reason)
            return False, reason, {"gate": "KILL_SWITCH", "status": "LOCKED"}

        # 2. CIRCUIT BREAKER & DRAWDOWN CHECK
        account_summary = ctrader_cloud_gateway.get_gateway_status()
        is_tripped, trip_reason, severity = risk_engine.check_circuit_breakers(account_summary, symbol=sym)
        if is_tripped:
            reason = f"VETO_CIRCUIT_BREAKER_LOCKED: {trip_reason}"
            logger.warning(reason)
            return False, reason, {"gate": "CIRCUIT_BREAKER", "status": "LOCKED", "severity": severity}

        # 3. ECONOMIC NEWS LOCKOUT WINDOW
        if not ignore_news_lockout:
            lockout = economic_calendar_service.check_lockout_status(symbol=sym)
            if lockout.get("is_locked_out"):
                reason = f"VETO_HIGH_IMPACT_NEWS_LOCKOUT: {lockout.get('lockout_reason')} ({lockout.get('minutes_to_next_high_impact_news')}m)"
                logger.warning(reason)
                return False, reason, {"gate": "NEWS_LOCKOUT", "status": "LOCKED", "event": lockout.get("next_event_name")}

        # 4. SPREAD THRESHOLD CHECK
        if current_spread_pips is not None:
            max_allowed_spread = cls.MAX_SPREAD_PIPS_MAP.get(sym, 3.0)
            if current_spread_pips > max_allowed_spread:
                reason = f"VETO_EXCESSIVE_SPREAD: Current spread {current_spread_pips:.1f} pips exceeds safety limit ({max_allowed_spread:.1f} pips)."
                logger.warning(reason)
                return False, reason, {"gate": "SPREAD_GUARD", "status": "EXCESSIVE_SPREAD", "current": current_spread_pips, "max": max_allowed_spread}

        # 5. MARKET DATA INTEGRITY & FRESHNESS CHECK
        if require_fresh_quotes:
            is_fresh, fresh_msg, q_obj = market_data_integrity_monitor.evaluate_price_freshness(sym, max_age=5.0)
            if not is_fresh:
                reason = f"VETO_STALE_MARKET_DATA: {fresh_msg}"
                logger.warning(reason)
                return False, reason, {"gate": "MARKET_DATA_HEALTH", "quote": q_obj}

        # 6. ANTI-FLIP SAFEGUARD CHECK
        anti_flip_ok, anti_flip_reason = position_manager_v3.check_anti_flip_guard(sym, act)
        if not anti_flip_ok:
            return False, anti_flip_reason, {"gate": "ANTI_FLIP_GUARD", "status": "COOLDOWN_ACTIVE"}

        # 7. MAX CONCURRENT POSITIONS CHECK
        active_positions = ctrader_cloud_gateway.GATEWAY_STATE.get("open_positions", [])
        if len(active_positions) >= cls.MAX_CONCURRENT_POSITIONS:
            reason = f"VETO_MAX_CONCURRENT_POSITIONS: Account already has {len(active_positions)} active position(s). Max allowed is {cls.MAX_CONCURRENT_POSITIONS}."
            logger.warning(reason)
            return False, reason, {"gate": "MAX_POSITIONS", "status": "LIMIT_REACHED", "count": len(active_positions)}

        # 8. STRICT SL/TP GEOMETRY, VOLATILITY-ADAPTIVE BUFFERS & R:R VALIDATION
        if sl_price is not None and tp_price is not None:
            is_gold = "XAU" in sym or "GOLD" in sym
            vol_state = volatility_engine.get_symbol_volatility(sym)
            min_sl_dist = vol_state.get("min_structural_sl_distance", 3.50 if is_gold else 0.0020)
            min_tp_dist = 5.00 if is_gold else 0.0030

            if act == "BUY":
                if not (sl_price < entry_price < tp_price):
                    reason = f"VETO_INVALID_SLTP_GEOMETRY: For BUY, must satisfy SL ({sl_price}) < Entry ({entry_price}) < TP ({tp_price})."
                    logger.warning(reason)
                    return False, reason, {"gate": "SLTP_GEOMETRY", "error": "INVERTED_SLTP"}
            elif act == "SELL":
                if not (tp_price < entry_price < sl_price):
                    reason = f"VETO_INVALID_SLTP_GEOMETRY: For SELL, must satisfy TP ({tp_price}) < Entry ({entry_price}) < SL ({sl_price})."
                    logger.warning(reason)
                    return False, reason, {"gate": "SLTP_GEOMETRY", "error": "INVERTED_SLTP"}

            risk_dist = abs(entry_price - sl_price)
            reward_dist = abs(tp_price - entry_price)
            if risk_dist <= 0:
                return False, "VETO_INVALID_STOP_LOSS: Stop loss cannot equal entry price.", {"gate": "RR_VALIDATION"}
            rr_ratio = round(reward_dist / risk_dist, 2)
            if rr_ratio < 1.5:
                reason = f"VETO_INSUFFICIENT_RR: Setup R:R {rr_ratio}:1 is below institutional minimum 1.5:1."
                logger.warning(reason)
                return False, reason, {"gate": "RR_VALIDATION", "rr_ratio": rr_ratio}

            if act == "BUY":
                if (entry_price - sl_price) < min_sl_dist:
                    reason = f"VETO_STOP_LOSS_TOO_TIGHT: SL distance ${entry_price - sl_price:.2f} is below minimum buffer ${min_sl_dist:.2f}."
                    logger.warning(reason)
                    return False, reason, {"gate": "SLTP_GEOMETRY", "error": "SL_TOO_TIGHT"}
                if (tp_price - entry_price) < min_tp_dist:
                    reason = f"VETO_TAKE_PROFIT_TOO_TIGHT: TP distance ${tp_price - entry_price:.2f} is below minimum target ${min_tp_dist:.2f}."
                    logger.warning(reason)
                    return False, reason, {"gate": "SLTP_GEOMETRY", "error": "TP_TOO_TIGHT"}
            elif act == "SELL":
                if (sl_price - entry_price) < min_sl_dist:
                    reason = f"VETO_STOP_LOSS_TOO_TIGHT: SL distance ${sl_price - entry_price:.2f} is below minimum buffer ${min_sl_dist:.2f}."
                    logger.warning(reason)
                    return False, reason, {"gate": "SLTP_GEOMETRY", "error": "SL_TOO_TIGHT"}
                if (entry_price - tp_price) < min_tp_dist:
                    reason = f"VETO_TAKE_PROFIT_TOO_TIGHT: TP distance ${entry_price - tp_price:.2f} is below minimum target ${min_tp_dist:.2f}."
                    logger.warning(reason)
                    return False, reason, {"gate": "SLTP_GEOMETRY", "error": "TP_TOO_TIGHT"}


        # 7. SIZING CLAMP VERIFICATION
        bal = float(account_summary.get("balance", 1000.0))
        sizing = risk_engine.calculate_position_size(
            symbol=sym,
            account_equity=bal,
            entry_price=entry_price,
            stop_loss=sl_price or (entry_price * 0.99)
        )
        calculated_vol = float(sizing.get("calculated_volume", 0.01))
        if volume > calculated_vol:
            if calculated_vol >= 0.01:
                volume = calculated_vol
            else:
                reason = f"VETO_VOLUME_EXCEEDS_RISK_LIMIT: Requested {volume} lots exceeds risk-safe volume {calculated_vol} lots."
                logger.warning(reason)
                return False, reason, {"gate": "POSITION_SIZING", "requested": volume, "max_allowed": calculated_vol}

        telemetry = {
            "gate": "ALL_GATES_PASSED",
            "status": "APPROVED",
            "symbol": sym,
            "action": act,
            "volume": volume,
            "account_balance": bal,
            "risk_dollars": sizing.get("risk_amount_dollars", 0.0),
            "is_live": account_summary.get("is_live", False)
        }

        return True, "SAFETY_GATES_PASSED: Setup meets all institutional safety standards.", telemetry

live_safety_gate = LiveSafetyGate()

import time
import logging
import datetime
from typing import Dict, Any, List, Optional, Tuple
from app.services.symbol_resolver import symbol_resolver
from app.services.structural_exit_engine import structural_exit_engine
from app.services.volatility_engine import volatility_engine
from app.services.market_data_integrity_monitor import market_data_integrity_monitor
from app.database.db import db
import ctrader_cloud_gateway

logger = logging.getLogger("TradeTalk.PositionManagerV3")

class PositionManagerV3:
    """
    Production Central Position Manager V3.
    Implements a strict 14-state lifecycle, true position-specific 1R accounting,
    an Authorized Exit Model, anti-flip safeguards, and entry stabilization.
    """

    ALLOWED_EXIT_MODELS = {
        "BROKER_STOP_LOSS",
        "BROKER_TAKE_PROFIT",
        "STRUCTURAL_INVALIDATION",
        "VALIDATED_TRAILING_STOP",
        "VALIDATED_BREAK_EVEN",
        "ACCOUNT_RISK_EMERGENCY",
        "BROKER_SAFETY_EVENT",
        "MANUAL_AUTHORIZED_CLOSE",
        "STRATEGY_EXIT"
    }

    VALID_STATES = {
        "CANDIDATE",
        "VALIDATED",
        "SUBMITTED",
        "BROKER_CONFIRMED",
        "ENTRY_STABILIZATION",
        "ACTIVE",
        "PROFIT_MANAGEMENT",
        "BREAK_EVEN_ELIGIBLE",
        "TRAILING",
        "PARTIAL_EXIT",
        "CLOSING",
        "CLOSED",
        "RECONCILING",
        "ERROR"
    }

    def __init__(self, stabilization_seconds: float = 15.0, anti_flip_cooldown_seconds: float = 60.0):
        self.stabilization_seconds = stabilization_seconds
        self.anti_flip_cooldown_seconds = anti_flip_cooldown_seconds
        self._managed_positions: Dict[str, Dict[str, Any]] = {}
        self._last_close_events: Dict[str, Dict[str, Any]] = {}

    def register_new_position(
        self,
        position_id: str,
        symbol: str,
        direction: str,
        volume: float,
        entry_price: float,
        initial_sl: float,
        initial_tp: float,
        ticket_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Registers and initializes a confirmed broker position with permanent 1R metrics."""
        norm_sym = symbol_resolver.normalize_symbol(symbol)
        pos_dir = direction.upper()
        
        initial_risk = round(abs(entry_price - initial_sl), 5)
        if initial_risk <= 0:
            # Fallback to 1.5x reference ATR if SL was not specified
            vol_state = volatility_engine.get_symbol_volatility(norm_sym)
            initial_risk = vol_state.get("recommended_sl_distance", 5.0)

        now = time.time()
        pos_record = {
            "position_id": str(position_id),
            "ticket_id": str(ticket_id or position_id),
            "symbol": norm_sym,
            "direction": pos_dir,
            "volume": float(volume),
            "entry_price": float(entry_price),
            "initial_sl": float(initial_sl),
            "current_sl": float(initial_sl),
            "initial_tp": float(initial_tp),
            "current_tp": float(initial_tp),
            "initial_risk_1r": initial_risk,
            "state": "ENTRY_STABILIZATION",
            "opened_at": now,
            "stabilization_end_time": now + self.stabilization_seconds,
            "break_even_locked": False,
            "trailing_active": False,
            "highest_price": float(entry_price),
            "lowest_price": float(entry_price),
            "realized_pnl": 0.0,
            "history": [f"{datetime.datetime.fromtimestamp(now, datetime.timezone.utc).isoformat()} -> ENTRY_STABILIZATION"]
        }

        self._managed_positions[str(position_id)] = pos_record
        logger.info(f"[PositionManagerV3] 🟢 Registered #{position_id} ({norm_sym} {pos_dir}) @ ${entry_price:.2f} | 1R = ${initial_risk:.2f} | State: ENTRY_STABILIZATION")
        return pos_record

    def get_position(self, position_id: str) -> Optional[Dict[str, Any]]:
        """Returns managed position record by ID."""
        return self._managed_positions.get(str(position_id))

    def get_active_positions(self) -> List[Dict[str, Any]]:
        """Returns list of all active non-closed positions."""
        return [p for p in self._managed_positions.values() if p.get("state") not in ("CLOSED", "ERROR")]

    def transition_state(self, position_id: str, new_state: str, reason: str = "") -> bool:
        """Transitions position to a new verified state."""

        pos = self._managed_positions.get(str(position_id))
        if not pos or new_state not in self.VALID_STATES:
            return False

        old_state = pos["state"]
        pos["state"] = new_state
        iso_now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        pos["history"].append(f"{iso_now} -> {new_state} ({reason})")
        logger.info(f"[PositionManagerV3] 🔄 #{position_id} State: {old_state} -> {new_state} ({reason})")
        return True

    def check_anti_flip_guard(self, symbol: str, proposed_direction: str) -> Tuple[bool, str]:
        """
        Anti-Flip Safeguard: Prevents immediate reverse trades after a position closes.
        Requires anti-flip cooldown or a validated fresh market structure break.
        """
        norm_sym = symbol_resolver.normalize_symbol(symbol)
        last_close = self._last_close_events.get(norm_sym)
        if not last_close:
            return True, "ANTI_FLIP_CLEAR"

        time_since_close = time.time() - last_close["closed_at"]
        last_dir = last_close["direction"]

        if proposed_direction.upper() != last_dir.upper() and time_since_close < self.anti_flip_cooldown_seconds:
            remaining = int(self.anti_flip_cooldown_seconds - time_since_close)
            reason = f"VETO_ANTI_FLIP_COOLDOWN: Opposite trade ({proposed_direction}) blocked for {remaining}s after #{last_close['position_id']} closed ({last_dir}) to prevent spread whiplash."
            logger.warning(reason)
            return False, reason

        return True, "ANTI_FLIP_CLEAR"

    def evaluate_managed_positions(self) -> List[Dict[str, Any]]:
        """
        Evaluates open positions against:
        1. Entry stabilization expiration
        2. Authorized Structural Invalidation
        3. Dynamic +1.0R Break-Even
        4. Dynamic +1.5R Trailing Stop
        """
        actions = []
        now = time.time()

        # Reconcile open list
        from app.services.ctrader_execution_service import ctrader_execution_service
        broker_positions = ctrader_execution_service.get_open_positions()
        active_ids = {str(p.get("id") or p.get("position_id")) for p in broker_positions}

        for pos_id, pos in list(self._managed_positions.items()):
            if pos["state"] in ("CLOSED", "ERROR"):
                continue

            # Check if position was closed at broker
            if pos_id not in active_ids and broker_positions:
                pos["state"] = "CLOSED"
                self._record_closed_position(pos, exit_model="BROKER_SETTLED")
                continue

            sym = pos["symbol"]
            pos_type = pos["direction"]
            entry_p = pos["entry_price"]
            one_r = pos["initial_risk_1r"]
            sl_p = pos["current_sl"]
            tp_p = pos["current_tp"]

            # Get live validated broker quote
            is_fresh, q_reason, tick = market_data_integrity_monitor.evaluate_price_freshness(sym, max_age=10.0)
            if not is_fresh or not tick:
                continue

            live_bid = tick["bid"]
            live_ask = tick["ask"]
            live_price = live_bid if pos_type == "BUY" else live_ask
            dollar_diff = (live_price - entry_p) if pos_type == "BUY" else (entry_p - live_price)
            current_r = round(dollar_diff / one_r, 2) if one_r > 0 else 0.0

            # 1. ENTRY STABILIZATION PHASE CHECK
            if pos["state"] == "ENTRY_STABILIZATION":
                if now >= pos["stabilization_end_time"]:
                    self.transition_state(pos_id, "ACTIVE", "Stabilization window completed.")
                else:
                    # During stabilization, ignore small noise
                    continue

            # 2. STRUCTURAL INVALIDATION EXIT CHECK (Completed candle confirmation)
            is_inv, inv_reason, inv_telemetry = structural_exit_engine.evaluate_structural_invalidation(
                symbol=sym,
                position_type=pos_type,
                entry_price=entry_p,
                initial_sl=pos["initial_sl"],
                timeframe="5m"
            )
            if is_inv:
                logger.info(f"[PositionManagerV3] 🛑 Executing Structural Invalidation Exit on #{pos_id}: {inv_reason}")
                close_res = ctrader_execution_service.close_position(pos_id)
                self.transition_state(pos_id, "CLOSED", inv_reason)
                self._record_closed_position(pos, exit_model="STRUCTURAL_INVALIDATION")
                actions.append({"action": "STRUCTURAL_INVALIDATION_EXIT", "position_id": pos_id, "result": close_res})
                continue

            # 3. DYNAMIC BREAK-EVEN (+1.0R PROFIT)
            if current_r >= 1.0 and not pos["break_even_locked"]:
                is_gold = "XAU" in sym or "GOLD" in sym
                be_buffer = 0.50 if is_gold else 0.0002
                new_sl = round(entry_p + be_buffer, 2 if is_gold else 5) if pos_type == "BUY" else round(entry_p - be_buffer, 2 if is_gold else 5)

                is_valid_monotonic = (pos_type == "BUY" and new_sl > sl_p) or (pos_type == "SELL" and (sl_p == 0 or new_sl < sl_p))
                if is_valid_monotonic:
                    logger.info(f"[PositionManagerV3] 🛡️ Locking Break-Even (+{current_r:.1f}R) on #{pos_id}: SL -> ${new_sl:.2f} (Retaining TP: ${tp_p:.2f})")
                    mod_res = ctrader_execution_service.modify_position_sltp(position_id=pos_id, new_sl=new_sl, new_tp=tp_p if tp_p > 0 else None)
                    pos["break_even_locked"] = True
                    pos["current_sl"] = new_sl
                    self.transition_state(pos_id, "BREAK_EVEN_ELIGIBLE", f"Secured at +{current_r:.1f}R")
                    actions.append({"action": "BREAK_EVEN_LOCKED", "position_id": pos_id, "new_sl": new_sl, "r_multiple": current_r})
                    continue

            # 4. DYNAMIC TRAILING STOP (+1.5R PROFIT)
            if current_r >= 1.5:
                # Lock in at least +0.5R profit
                trail_lock_p = round(entry_p + (0.5 * one_r), 2 if "XAU" in sym else 5) if pos_type == "BUY" else round(entry_p - (0.5 * one_r), 2 if "XAU" in sym else 5)
                is_valid_trail = (pos_type == "BUY" and trail_lock_p > pos["current_sl"]) or (pos_type == "SELL" and (pos["current_sl"] == 0 or trail_lock_p < pos["current_sl"]))
                if is_valid_trail:
                    logger.info(f"[PositionManagerV3] 🏃 Advancing Trailing Stop (+{current_r:.1f}R) on #{pos_id}: SL -> ${trail_lock_p:.2f}")
                    mod_res = ctrader_execution_service.modify_position_sltp(position_id=pos_id, new_sl=trail_lock_p, new_tp=tp_p if tp_p > 0 else None)
                    pos["current_sl"] = trail_lock_p
                    pos["trailing_active"] = True
                    self.transition_state(pos_id, "TRAILING", f"Trailing active at +{current_r:.1f}R")
                    actions.append({"action": "TRAILING_STOP_ADVANCED", "position_id": pos_id, "new_sl": trail_lock_p, "r_multiple": current_r})

        return actions

    def _record_closed_position(self, pos: Dict[str, Any], exit_model: str):
        sym = pos["symbol"]
        self._last_close_events[sym] = {
            "position_id": pos["position_id"],
            "direction": pos["direction"],
            "closed_at": time.time(),
            "exit_model": exit_model
        }
        db.log_audit(
            event_type="POSITION_CLOSED",
            actor="PositionManagerV3",
            details=f"Position #{pos['position_id']} ({sym} {pos['direction']}) closed via {exit_model}."
        )

    def get_position_state(self, position_id: str) -> Optional[Dict[str, Any]]:
        return self._managed_positions.get(str(position_id))

    def get_all_managed_positions(self) -> List[Dict[str, Any]]:
        return list(self._managed_positions.values())

position_manager_v3 = PositionManagerV3()

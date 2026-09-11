import time
import logging
import datetime
from typing import Dict, Any, List, Optional
from app.services.ctrader_execution_service import ctrader_execution_service
from app.services.market_feed_v2 import get_market_snapshot
from app.database.db import db
import ctrader_cloud_gateway

from app.services.position_manager_v3 import position_manager_v3

logger = logging.getLogger("TradeTalk.PositionSentinel")

class PositionSentinel:
    """
    Authoritative Autonomous Position Sentinel & Risk Lock Engine.
    Rules:
    1. NEVER closes losing positions based on AI indicator/trend fluctuations.
       Trades must breathe and respect their configured Stop Loss or Take Profit.
    2. Locks in Break-Even ONLY after substantial profit (+1.0R based on position initial risk).
    3. Preserves existing Take Profit when modifying Stop Loss (never wipes TP).
    4. Enforces strict directional monotonicity (BUY SL moves UP, SELL SL moves DOWN).
    5. Trails Stop Loss to lock in runner profits without expanding risk.
    """

    def __init__(self):
        self.last_sentinel_scan_ts = 0.0

    def evaluate_open_positions(self) -> List[Dict[str, Any]]:
        """
        Scans all active open positions against genuine real-time market data
        and safely manages Break-Even and Trailing Stop modifications.
        """
        now = time.time()
        self.last_sentinel_scan_ts = now
        if not ctrader_cloud_gateway.get_gateway_status().get("execution_ready"):
            return []
        
        # 1. Run PositionManagerV3 evaluation
        v3_actions = position_manager_v3.evaluate_managed_positions()

        positions = ctrader_execution_service.get_open_positions()
        if not positions:
            return v3_actions

        actions_taken = list(v3_actions)

        for pos in positions:
            pos_id = pos.get("id") or pos.get("position_id")
            if not pos_id:
                continue

            sym = str(pos.get("symbol", "XAUUSD")).upper()
            pos_type = str(pos.get("type") or pos.get("action") or "BUY").upper()
            entry_p = float(pos.get("entry_price") or 0.0)
            sl_p = float(pos.get("sl_price") or pos.get("sl") or 0.0)
            tp_p = float(pos.get("tp_price") or pos.get("tp") or 0.0)
            current_pnl = float(pos.get("net_profit") or pos.get("unrealized_pnl") or 0.0)
            be_locked = bool(pos.get("break_even_locked", False))

            if entry_p <= 0:
                continue

            # Calculate position-specific 1R
            initial_risk_1r = abs(entry_p - sl_p) if (sl_p > 0 and abs(entry_p - sl_p) > 0.5) else 5.0

            # Fetch fresh live market data
            market_data = ctrader_cloud_gateway.get_live_price(sym)
            if not market_data:
                continue
            live_price = float(market_data["bid"] if pos_type == "BUY" else market_data["ask"])

            is_gold = "XAU" in sym or "GOLD" in sym
            pip_size = 0.01 if is_gold else 0.0001
            dollar_diff = (live_price - entry_p) if pos_type == "BUY" else (entry_p - live_price)
            current_r = dollar_diff / initial_risk_1r if initial_risk_1r > 0 else 0.0

            # -------------------------------------------------------------
            # 1. AUTONOMOUS BREAK-EVEN LOCK (+1.0R profit)
            # -------------------------------------------------------------
            if current_r >= 1.0 and not be_locked:
                buffer = 0.50 if is_gold else (pip_size * 5)
                new_sl = round(entry_p + buffer, 2 if is_gold else 5) if pos_type == "BUY" else round(entry_p - buffer, 2 if is_gold else 5)
                
                # Verify Monotonicity: BUY new_sl > current_sl; SELL new_sl < current_sl
                is_valid_monotonic = (pos_type == "BUY" and (sl_p == 0 or new_sl > sl_p)) or \
                                     (pos_type == "SELL" and (sl_p == 0 or new_sl < sl_p))
                
                if is_valid_monotonic:
                    logger.info(f"[Position Sentinel] 🛡️ Locking Break-Even on #{pos_id} ({sym} {pos_type}) @ ${new_sl:.2f} (Profit: +${dollar_diff:.2f}, Retaining TP: ${tp_p}).")
                    mod_res = ctrader_execution_service.modify_position_sltp(
                        position_id=pos_id,
                        new_sl=new_sl,
                        new_tp=tp_p if tp_p > 0 else None
                    )
                    pos["break_even_locked"] = True
                    pos["sl_price"] = new_sl
                    db.log_audit(
                        event_type="BREAK_EVEN_LOCKED",
                        actor="PositionSentinel",
                        details=f"Position #{pos_id} ({sym} {pos_type}) moved to Break-Even at ${new_sl:.2f} (Profit: +${dollar_diff:.2f}). Existing TP ${tp_p} preserved."
                    )
                    actions_taken.append({
                        "action": "BREAK_EVEN_LOCKED",
                        "position_id": pos_id,
                        "new_sl": new_sl,
                        "retained_tp": tp_p,
                        "result": mod_res
                    })
                    continue

            # -------------------------------------------------------------
            # 2. AUTONOMOUS TRAILING STOP (+1.5R profit)
            # -------------------------------------------------------------
            if current_r >= 1.5:
                lock_dist = round(0.5 * initial_risk_1r, 2 if is_gold else 5)
                trail_sl = round(entry_p + lock_dist, 2 if is_gold else 5) if pos_type == "BUY" else round(entry_p - lock_dist, 2 if is_gold else 5)
                
                is_valid_trail = (pos_type == "BUY" and trail_sl > sl_p) or \
                                 (pos_type == "SELL" and (sl_p == 0 or trail_sl < sl_p))
                
                if is_valid_trail:
                    logger.info(f"[Position Sentinel] 🏃 Trailing Stop Activated on #{pos_id}: SL -> ${trail_sl:.2f} to secure +${lock_dist:.2f} profit (Retaining TP: ${tp_p}).")
                    mod_res = ctrader_execution_service.modify_position_sltp(
                        position_id=pos_id,
                        new_sl=trail_sl,
                        new_tp=tp_p if tp_p > 0 else None
                    )
                    pos["sl_price"] = trail_sl
                    db.log_audit(
                        event_type="TRAILING_STOP_ADVANCED",
                        actor="PositionSentinel",
                        details=f"Position #{pos_id} Trailing Stop moved to ${trail_sl:.2f}, securing +${lock_dist:.2f} profit. Existing TP ${tp_p} preserved."
                    )
                    actions_taken.append({
                        "action": "TRAILING_STOP_ADVANCED",
                        "position_id": pos_id,
                        "new_sl": trail_sl,
                        "retained_tp": tp_p,
                        "result": mod_res
                    })

        return actions_taken

position_sentinel = PositionSentinel()



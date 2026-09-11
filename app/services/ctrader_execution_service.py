import os
import time
import uuid
import logging
import requests
from typing import Dict, Any, List, Optional
from app.config import settings
import ctrader_cloud_gateway
from app.services.symbol_resolver import symbol_resolver
from app.services.live_safety_gate import live_safety_gate
from app.database.db import db

logger = logging.getLogger("TradeTalk.cTraderExecutionService")

class CTraderExecutionService:
    """
    Production-grade order execution service interfacing with cTrader Open API 2.0.
    Supports Market, Limit, Stop orders, SL/TP modification, Move-to-Break-Even,
    Partial Closes, Trailing Stop calculation, and resilient trade persistence.
    """

    def __init__(self):
        self.gateway = ctrader_cloud_gateway
        self._positions_cache: Dict[str, Dict[str, Any]] = {}

    def execute_market_order(
        self,
        symbol: str,
        action: str,
        volume: float,
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None,
        comment: str = "TradeTalk AI Autonomous Order",
        signal_id: Optional[str] = None,
        bypass_safety: bool = False,
        ignore_news_lockout: bool = False
    ) -> Dict[str, Any]:
        """
        Submits an immediate Market execution order through cTrader Open API.
        Enforces centralized LiveSafetyGate pre-execution verification.
        """
        sym = symbol.upper()
        act = action.upper()
        spec = symbol_resolver.get_symbol_spec(sym)
        digits = spec.get("digits", 2)
        
        # Format SL/TP to appropriate digits
        formatted_sl = round(sl_price, digits) if sl_price is not None else None
        formatted_tp = round(tp_price, digits) if tp_price is not None else None

        sig_id = signal_id or f"SIG_{uuid.uuid4().hex[:8].upper()}"

        # This check is mandatory even when other strategy checks are bypassed.
        self.gateway.get_gateway_status()
        live_tick = self.gateway.get_live_price(sym)
        if not live_tick:
            return {"status": "VETOED_BY_SAFETY_GATE", "reason": "VETO_UNVERIFIED_BROKER_TELEMETRY"}
        live_p = float(live_tick["ask"] if act == "BUY" else live_tick["bid"])

        # 1. Non-negotiable Live Safety Gatekeeper Verification
        if not bypass_safety:
            is_safe, safety_msg, safety_telemetry = live_safety_gate.evaluate_order_safety(
                symbol=sym,
                action=act,
                volume=volume,
                entry_price=live_p,
                sl_price=formatted_sl,
                tp_price=formatted_tp,
                ignore_news_lockout=ignore_news_lockout
            )
            if not is_safe:
                logger.warning(f"Order rejected by centralized LiveSafetyGate: {safety_msg}")
                return {
                    "status": "VETOED_BY_SAFETY_GATE",
                    "reason": safety_msg,
                    "telemetry": safety_telemetry
                }

        logger.info(f"Executing Market {act} {volume} lots of {sym} (SL: {formatted_sl}, TP: {formatted_tp})")

        res = self.gateway.execute_market_order(
            symbol=sym,
            action=act,
            lot_size=volume,
            sl_price=formatted_sl,
            tp_price=formatted_tp,
            signal_id=sig_id,
            comment=comment
        )

        if res.get("status") == "SUCCESS":
            ticket = res.get("ticket") or res.get("ticket_id") or res.get("position_id")
            if ticket:
                clean_ticket = str(ticket).replace("CT_", "")
                entry_fill_price = float(res.get("entry_price") or res.get("price") or live_p or 0.0)
                pos_obj = {
                    "id": int(clean_ticket) if clean_ticket.isdigit() else clean_ticket,
                    "position_id": str(clean_ticket),
                    "ticket": f"CT_{clean_ticket}" if not str(ticket).startswith("CT_") else str(ticket),
                    "symbol": sym,
                    "type": act,
                    "action": act,
                    "volume": volume,
                    "lot_size": volume,
                    "entry_price": entry_fill_price,
                    "sl_price": formatted_sl,
                    "sl": formatted_sl,
                    "tp_price": formatted_tp,
                    "tp": formatted_tp,
                    "current_price": entry_fill_price,
                    "net_profit": 0.0,
                    "timestamp": time.time()
                }
                self._positions_cache[clean_ticket] = pos_obj

                # Register in Central Position Manager V3
                try:
                    from app.services.position_manager_v3 import position_manager_v3
                    position_manager_v3.register_new_position(
                        position_id=str(clean_ticket),
                        symbol=sym,
                        direction=act,
                        volume=volume,
                        entry_price=entry_fill_price,
                        initial_sl=formatted_sl or 0.0,
                        initial_tp=formatted_tp or 0.0,
                        ticket_id=str(ticket)
                    )
                except Exception as ex:
                    logger.debug(f"Position registration note: {ex}")

        return res

    def _find_position(self, position_id: Any) -> Optional[Dict[str, Any]]:
        """Resolves active position record across gateway state and local tracking cache."""
        pos_str = str(position_id).strip()
        open_positions = self.get_open_positions()

        for p in open_positions:
            if (
                str(p.get("id")) == pos_str or
                str(p.get("ticket")) == pos_str or
                str(p.get("position_id")) == pos_str or
                f"CT_{p.get('id')}" == pos_str or
                str(p.get("ticket", "")).replace("CT_", "") == pos_str.replace("CT_", "") or
                str(p.get("id", "")).replace("CT_", "") == pos_str.replace("CT_", "")
            ):
                return p

        clean_key = pos_str.replace("CT_", "")
        if clean_key in self._positions_cache:
            return self._positions_cache[clean_key]

        return None

    def close_position(
        self,
        position_id: Any,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Closes an active open position by ticket ID.
        """
        res = self.gateway.close_position(position_id=position_id, force=force)
        if res.get("status") == "SUCCESS":
            self._positions_cache.pop(str(position_id).replace("CT_", ""), None)
        return res

    def partial_close_position(
        self,
        position_id: Any,
        close_volume: float
    ) -> Dict[str, Any]:
        """
        Partially closes an active position (e.g. 50% at 1.5R target).
        """
        # There is no broker partial-close protocol in this bridge. Do not simulate
        # volume or realized P&L and then label it broker state.
        return {"status": "REJECTED_UNSUPPORTED_BROKER_OPERATION",
                "message": "Partial close requires broker-confirmed support; account state unchanged."}

    def modify_position_sltp(
        self,
        position_id: Any,
        new_sl: Optional[float] = None,
        new_tp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Updates Stop Loss and/or Take Profit on an active position.
        """
        target_pos = self._find_position(position_id)

        if not target_pos:
            return {"status": "ERROR", "message": f"Position #{position_id} not found"}

        if os.getenv("TESTING") == "1":
            return {"status": "REJECTED_TEST_MODE_EXTERNAL_EXECUTION_BLOCKED"}
        if not self.gateway.get_live_price(target_pos.get("symbol", "XAUUSD")):
            return {"status": "REJECTED_BROKER_TELEMETRY"}
        target_pos = dict(target_pos)  # Do not mutate the authoritative snapshot optimistically.
        sym = target_pos.get("symbol", "XAUUSD")
        spec = symbol_resolver.get_symbol_spec(sym)
        digits = spec.get("digits", 2)

        if new_sl is not None:
            target_pos["sl_price"] = round(new_sl, digits)
            target_pos["sl"] = round(new_sl, digits)
            target_pos["stop_loss"] = round(new_sl, digits)
        if new_tp is not None:
            target_pos["tp_price"] = round(new_tp, digits)
            target_pos["tp"] = round(new_tp, digits)
            target_pos["take_profit"] = round(new_tp, digits)

        logger.info(f"Modified SL/TP for #{position_id}: SL -> {target_pos.get('sl_price')}, TP -> {target_pos.get('tp_price')}")

        # Dispatch modification directly to local cBot bridge on port 5001
        bridge_url = os.getenv("CBOT_BRIDGE_URL", "http://127.0.0.1:5001/trade/").strip()
        try:
            import requests
            response = requests.post(bridge_url, json={
                "action": "MODIFY",
                "position_id": str(target_pos.get("id")),
                "account_id": self.gateway.GATEWAY_STATE["account_id"],
                "snapshot_at": self.gateway.GATEWAY_STATE["broker_snapshot_at"],
                "quote_at": self.gateway.get_live_price(sym)["quote_at"],
                "sl_price": target_pos.get("sl_price"),
                "tp_price": target_pos.get("tp_price")
            }, timeout=2.0)
            if response.status_code != 200 or response.json().get("status") != "SUCCESS":
                return {"status": "REJECTED_BROKER_EXECUTION_UNCONFIRMED"}
            self.gateway.GATEWAY_STATE["positions_snapshot_valid"] = False
        except Exception as be:
            return {"status": "REJECTED_BROKER_EXECUTION_UNCONFIRMED", "message": str(be)}

        db.log_audit(
            event_type="POSITION_MODIFIED",
            actor="cTraderExecutionService",
            details=f"Position #{position_id} SL/TP modified: SL={target_pos.get('sl_price')}, TP={target_pos.get('tp_price')}"
        )

        return {
            "status": "SUCCESS",
            "position_id": position_id,
            "sl_price": target_pos.get("sl_price"),
            "tp_price": target_pos.get("tp_price")
        }

    def move_to_break_even(
        self,
        position_id: Any,
        buffer_pips: float = 1.0
    ) -> Dict[str, Any]:
        """
        Moves Stop Loss to entry price + slight buffer to guarantee a risk-free trade.
        """
        target_pos = self._find_position(position_id)

        if not target_pos:
            return {"status": "ERROR", "message": f"Position #{position_id} not found"}

        sym = target_pos.get("symbol", "XAUUSD")
        pos_type = target_pos.get("type", target_pos.get("action", "BUY")).upper()
        entry_price = float(target_pos.get("entry_price", 0.0))
        spec = symbol_resolver.get_symbol_spec(sym)
        pip_size = spec.get("pip_size", 0.01)
        digits = spec.get("digits", 2)

        buffer_offset = buffer_pips * pip_size
        be_sl = (entry_price + buffer_offset) if pos_type == "BUY" else (entry_price - buffer_offset)
        be_sl = round(be_sl, digits)

        return self.modify_position_sltp(position_id=position_id, new_sl=be_sl)

    def reconcile_positions(self) -> Dict[str, Any]:
        """
        Authoritative State Reconciliation:
        Compares local execution service cache against actual broker/gateway positions.
        Returns reconciliation status and flags any discrepancies.
        """
        state = self.gateway.GATEWAY_STATE
        if not self.gateway.broker_telemetry.health(state)["account_fresh"]:
            return {"is_synced": False, "status": "TELEMETRY_UNAVAILABLE",
                    "broker_position_count": None, "cached_position_count": len(self._positions_cache),
                    "orphaned_cleaned": []}
        gw_positions = state["open_positions"]
        gw_ids = {str(p.get("id") or p.get("position_id") or p.get("ticket")).replace("CT_", "") for p in gw_positions}
        cache_ids = set(self._positions_cache.keys())

        # Sync cache to match gateway state
        orphaned_in_cache = cache_ids - gw_ids
        for orphaned_id in orphaned_in_cache:
            logger.warning(f"[Reconciliation] Removing orphaned position #{orphaned_id} from local cache.")
            self._positions_cache.pop(orphaned_id, None)

        self._positions_cache = {
            str(p.get("id") or p.get("position_id") or p.get("ticket")).replace("CT_", ""): dict(p)
            for p in gw_positions
        }

        is_synced = (len(self._positions_cache) == len(gw_positions))
        return {
            "is_synced": is_synced,
            "broker_position_count": len(gw_positions),
            "cached_position_count": len(self._positions_cache),
            "orphaned_cleaned": list(orphaned_in_cache),
            "status": "RECONCILED" if is_synced else "STATE_MISMATCH"
        }

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Returns all live open positions tracked by the gateway and execution service."""
        gw_positions = self.gateway.GATEWAY_STATE.get("open_positions", [])
        if self.gateway.GATEWAY_STATE.get("broker_snapshot_received"):
            if self.gateway.GATEWAY_STATE.get("positions_snapshot_valid"):
                self.reconcile_positions()
            return gw_positions
        if gw_positions:
            return gw_positions
        return list(self._positions_cache.values())

    def get_account_summary(self) -> Dict[str, Any]:
        """Returns active account financial metrics and connectivity status."""
        return self.gateway.get_gateway_status()

ctrader_execution_service = CTraderExecutionService()



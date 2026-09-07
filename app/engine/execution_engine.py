import uuid
import datetime
import logging
from typing import Dict, Any, Optional
from app.config import settings
from app.database.models import SignalPayload, ConsensusResult
from app.database.db import db
import cbot_bridge

logger = logging.getLogger("TradeTalk.ExecutionEngine")

class ExecutionEngine:
    def __init__(self):
        self.mode = settings.TRADING_MODE # 'PAPER', 'DEMO', 'LIVE'

    def set_trading_mode(self, new_mode: str, confirmed: bool = False) -> Dict[str, Any]:
        mode_clean = new_mode.upper()
        if mode_clean not in ("PAPER", "DEMO", "LIVE"):
            return {"status": "ERROR", "message": f"Invalid trading mode '{new_mode}'"}

        if mode_clean == "LIVE" and not confirmed:
            return {
                "status": "CONFIRMATION_REQUIRED",
                "message": "LIVE trading requires explicit user activation and risk limits acceptance.",
                "current_mode": self.mode
            }

        prev_mode = self.mode
        self.mode = mode_clean
        db.log_audit(
            event_type="TRADING_MODE_CHANGED",
            actor="UserOrAdmin",
            details=f"Trading mode transitioned from {prev_mode} to {self.mode}"
        )
        return {
            "status": "SUCCESS",
            "previous_mode": prev_mode,
            "current_mode": self.mode,
            "message": f"Trading mode is now active: {self.mode}"
        }

    def dispatch_trade(self, consensus_res: ConsensusResult, signal: SignalPayload) -> Dict[str, Any]:
        """
        Routes approved signal to appropriate execution pipeline (Paper, Demo, or Live).
        """
        if consensus_res.decision_status != "APPROVED":
            return {
                "status": "EXECUTION_ABORTED_NOT_APPROVED",
                "reason": f"Signal status is {consensus_res.decision_status}"
            }

        trade_id = f"TRD_{uuid.uuid4().hex[:8].upper()}"
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        vol = signal.dict().get("volume", settings.DEFAULT_LOT_SIZE)

        # 1. PAPER TRADING MODE (High-Fidelity Virtual Execution)
        if self.mode == "PAPER":
            paper_trade = {
                "id": trade_id,
                "signal_id": consensus_res.signal_id,
                "mode": "PAPER",
                "broker_order_id": f"PAPER_ORD_{trade_id}",
                "ticket_id": f"PT_{trade_id}",
                "symbol": signal.symbol,
                "direction": signal.action.upper(),
                "entry_price": signal.entry_price,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "volume": vol,
                "profit_loss": 0.0,
                "pips": 0.0,
                "status": "OPEN",
                "opened_at": now_iso
            }
            db.save_trade(paper_trade)
            db.log_audit(
                event_type="PAPER_TRADE_EXECUTED",
                actor="ExecutionEngine",
                details=f"Opened Paper Trade {trade_id}: {signal.action} {vol} lots of {signal.symbol} @ ${signal.entry_price:.2f}"
            )
            return {
                "status": "EXECUTED_PAPER",
                "mode": "PAPER",
                "trade_id": trade_id,
                "ticket": paper_trade["ticket_id"],
                "symbol": signal.symbol,
                "action": signal.action,
                "entry_price": signal.entry_price,
                "sl": signal.stop_loss,
                "tp": signal.take_profit,
                "volume": vol,
                "executed_at": now_iso
            }

        # 2. DEMO OR LIVE TRADING MODE (cTrader Bridge Direct Queue)
        elif self.mode in ("DEMO", "LIVE"):
            cbot_sig_id = f"CT_{trade_id}"
            queue_res = cbot_bridge.queue_trade_for_cbot(
                symbol=signal.symbol,
                action=signal.action,
                lot_size=vol,
                sl_price=signal.stop_loss,
                tp_price=signal.take_profit,
                signal_id=cbot_sig_id
            )

            if queue_res.get("status", "").startswith("REJECTED"):
                return queue_res

            live_trade = {
                "id": trade_id,
                "signal_id": consensus_res.signal_id,
                "mode": self.mode,
                "broker_order_id": f"Pending cTrader Fill ({cbot_sig_id})",
                "ticket_id": cbot_sig_id,
                "symbol": signal.symbol,
                "direction": signal.action.upper(),
                "entry_price": signal.entry_price,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "volume": vol,
                "profit_loss": 0.0,
                "pips": 0.0,
                "status": "QUEUED",
                "opened_at": now_iso
            }
            db.save_trade(live_trade)
            db.log_audit(
                event_type=f"{self.mode}_TRADE_QUEUED",
                actor="ExecutionEngine",
                details=f"Dispatched {self.mode} order to cTrader: {signal.action} {vol} lots of {signal.symbol} (Ticket: {cbot_sig_id})"
            )
            return {
                "status": f"QUEUED_TO_CBOT_{self.mode}",
                "mode": self.mode,
                "trade_id": trade_id,
                "ticket": cbot_sig_id,
                "symbol": signal.symbol,
                "action": signal.action,
                "entry_price": signal.entry_price,
                "sl": signal.stop_loss,
                "tp": signal.take_profit,
                "volume": vol,
                "executed_at": now_iso
            }

        return {"status": "UNKNOWN_MODE"}

execution_engine = ExecutionEngine()

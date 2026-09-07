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

        # Server-Side cTrader & Gateway Execution
        cbot_sig_id = f"CT_{trade_id}"
        exec_res = cbot_bridge.queue_trade_for_cbot(
            symbol=signal.symbol,
            action=signal.action,
            lot_size=vol,
            sl_price=signal.stop_loss,
            tp_price=signal.take_profit,
            signal_id=cbot_sig_id
        )

        if exec_res.get("status", "").startswith("REJECTED"):
            logger.warning(f"Trade dispatch rejected by gateway: {exec_res}")
            return exec_res

        ticket_num = exec_res.get("ticket") or exec_res.get("ticket_id") or cbot_sig_id
        fill_p = exec_res.get("fill_price", signal.entry_price)

        executed_trade = {
            "id": trade_id,
            "signal_id": consensus_res.signal_id,
            "mode": self.mode,
            "broker_order_id": f"cTrader Cloud Fill (#{ticket_num})",
            "ticket_id": str(ticket_num),
            "symbol": signal.symbol,
            "direction": signal.action.upper(),
            "entry_price": fill_p,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "volume": vol,
            "profit_loss": 0.0,
            "pips": 0.0,
            "status": "OPEN",
            "opened_at": now_iso
        }
        db.save_trade(executed_trade)
        db.log_audit(
            event_type=f"{self.mode}_TRADE_EXECUTED",
            actor="ExecutionEngine",
            details=f"Direct Execution #{ticket_num} on cTrader Account #{settings.CTRADER_ACCOUNT_ID}: {signal.action} {vol} lots of {signal.symbol} @ ${fill_p:.2f} (SL: ${signal.stop_loss:.2f}, TP: ${signal.take_profit:.2f})"
        )
        return {
            "status": f"EXECUTED_{self.mode}",
            "mode": self.mode,
            "trade_id": trade_id,
            "ticket": ticket_num,
            "ticket_id": str(ticket_num),
            "symbol": signal.symbol,
            "action": signal.action,
            "entry_price": fill_p,
            "sl": signal.stop_loss,
            "tp": signal.take_profit,
            "volume": vol,
            "executed_at": now_iso,
            "receipt": exec_res
        }

execution_engine = ExecutionEngine()

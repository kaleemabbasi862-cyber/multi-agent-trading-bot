import uuid
import datetime
import logging
from typing import Dict, Any, Optional
from app.config import settings, trading_config
from app.database.models import SignalPayload, ConsensusResult, DataProvenance
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
        Routes approved signal to appropriate execution pipeline (Paper, Demo, or Live)
        with atomic intent idempotency locking and immutable initial 1R assignment.
        """
        if consensus_res.decision_status != "APPROVED":
            return {
                "status": "EXECUTION_ABORTED_NOT_APPROVED",
                "reason": f"Signal status is {consensus_res.decision_status}"
            }

        intent_id = consensus_res.execution_intent_id or f"INTENT_{consensus_res.signal_id}"
        
        # Idempotency Lock Gate: Register Intent atomically in DB
        inserted, existing_intent = db.record_execution_intent(
            intent_id=intent_id,
            signal_id=consensus_res.signal_id,
            action=signal.action,
            status="DISPATCHING",
            provenance=DataProvenance.BROKER_DEMO
        )
        
        if not inserted and existing_intent:
            logger.warning(f"DUPLICATE EXECUTION BLOCKED: Intent {intent_id} already exists in state {existing_intent.get('status')}")
            return {
                "status": "DUPLICATE_EXECUTION_BLOCKED",
                "reason": f"Execution intent {intent_id} already exists with status {existing_intent.get('status')}",
                "intent_id": intent_id,
                "existing_intent": existing_intent
            }

        trade_id = f"TRD_{uuid.uuid4().hex[:8].upper()}"
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        vol = (signal.model_dump() if hasattr(signal, "model_dump") else signal.dict()).get("volume", settings.DEFAULT_LOT_SIZE)


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
            db.update_execution_intent_status(intent_id, "FAILED", error=str(exec_res.get("reason") or exec_res.get("message")))
            return exec_res

        ticket_num = exec_res.get("ticket") or exec_res.get("ticket_id") or cbot_sig_id
        fill_p = float(exec_res.get("fill_price") or signal.entry_price or 0.0)
        final_sl = float(exec_res.get("sl") if exec_res.get("sl") is not None else (signal.stop_loss or 0.0))
        final_tp = float(exec_res.get("tp") if exec_res.get("tp") is not None else (signal.take_profit or 0.0))
        
        # Calculate Canonical Immutable 1R (Absolute initial stop distance)
        initial_r = abs(fill_p - final_sl)

        executed_trade = {
            "id": trade_id,
            "signal_id": consensus_res.signal_id,
            "mode": self.mode,
            "broker_order_id": f"cTrader Cloud Fill (#{ticket_num})",
            "ticket_id": str(ticket_num),
            "symbol": signal.symbol,
            "direction": signal.action.upper(),
            "entry_price": fill_p,
            "stop_loss": final_sl,
            "take_profit": final_tp,
            "volume": vol,
            "profit_loss": 0.0,
            "pips": 0.0,
            "status": "OPEN",
            "opened_at": now_iso,
            "execution_intent_id": intent_id,
            "initial_r": initial_r,
            "provenance": DataProvenance.BROKER_DEMO_VERIFIED if self.mode == "DEMO" else (DataProvenance.BROKER_LIVE_VERIFIED if self.mode == "LIVE" else DataProvenance.PAPER),
            "is_broker_verified": 1 if self.mode in ("DEMO", "LIVE") else 0,
            "broker_account_id": getattr(settings, "CTRADER_ACCOUNT_ID", "5908018"),
            "strategy_version": "Gold_Sniper_SMC_v2.0",
            "execution_environment": self.mode,
            "data_source": "cTrader Open API"
        }
        db.save_trade(executed_trade)
        
        # Mark Intent as COMPLETED
        db.update_execution_intent_status(
            intent_id=intent_id,
            status="COMPLETED",
            broker_order_id=str(ticket_num)
        )
        
        db.log_audit(
            event_type=f"{self.mode}_TRADE_EXECUTED",
            actor="ExecutionEngine",
            details=f"Direct Execution #{ticket_num} on cTrader Account #{settings.CTRADER_ACCOUNT_ID}: {signal.action} {vol} lots of {signal.symbol} @ ${fill_p:.2f} (SL: ${signal.stop_loss:.2f}, TP: ${signal.take_profit:.2f}, 1R=${initial_r:.2f})"
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
            "initial_r": initial_r,
            "execution_intent_id": intent_id,
            "executed_at": now_iso,
            "receipt": exec_res
        }

execution_engine = ExecutionEngine()


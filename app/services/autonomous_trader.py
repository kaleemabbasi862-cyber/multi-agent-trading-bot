import time
import logging
from typing import Dict, Any, Optional, List
import uuid
import datetime
from app.database.models import SignalPayload
from app.engine.consensus_engine import consensus_engine
from app.services.ctrader_execution_service import ctrader_execution_service
from app.services.live_safety_gate import live_safety_gate
from app.services.risk_engine import risk_engine
from app.services.economic_calendar import economic_calendar_service
from app.database.db import db
import ctrader_cloud_gateway

logger = logging.getLogger("TradeTalk.AutonomousTrader")

class AutonomousTrader:
    """
    Phase 10: Autonomous Multi-Agent Trading Engine.
    Coordinates continuous market scanning, 6-agent consensus evaluation,
    safety gating, execution via cTrader Open API, and post-entry trade management.
    """

    def __init__(self):
        self.is_running = False
        self.active_symbol = "XAUUSD"
        self.trailing_enabled = True
        self.break_even_enabled = True
        self.be_threshold_r = 1.0 # Move to BE at 1R profit
        self.last_scan_time = 0.0

    def start(self):
        if not ctrader_cloud_gateway.get_gateway_status().get("execution_ready"):
            self.is_running = False
            return False
        self.is_running = True
        logger.info("Autonomous Multi-Agent Trading loop STARTED.")
        db.log_audit("AUTONOMOUS_TRADER_STARTED", "AutonomousTrader", "Autonomous trading mode activated.")

    def stop(self):
        self.is_running = False
        logger.info("Autonomous Multi-Agent Trading loop STOPPED.")
        db.log_audit("AUTONOMOUS_TRADER_STOPPED", "AutonomousTrader", "Autonomous trading mode deactivated.")

    def toggle(self) -> bool:
        if self.is_running:
            self.stop()
        else:
            self.start()
        return self.is_running

    def process_market_setup(
        self,
        symbol: str,
        action: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        timeframe: str = "15m",
        market_context: Optional[Dict[str, Any]] = None,
        force_execute: bool = False
    ) -> Dict[str, Any]:
        """
        Full-lifecycle pipeline:
        1. 6-Agent Consensus Evaluation
        2. Position Sizing
        3. Live Safety Gate verification
        4. cTrader Order Execution
        5. Decision DNA & Audit Logging
        """
        sym = symbol.upper()
        act = action.upper()
        now = datetime.datetime.now(datetime.timezone.utc)
        sig_id = f"SIG_AUTO_{uuid.uuid4().hex[:8].upper()}"

        logger.info(f"Evaluating Autonomous Setup: {act} {sym} @ {entry_price} (SL: {stop_loss}, TP: {take_profit})")

        acc_summary = ctrader_cloud_gateway.get_gateway_status()
        if not ctrader_cloud_gateway.broker_telemetry.health(ctrader_cloud_gateway.GATEWAY_STATE, sym)["execution_ready"]:
            return {"status": "BLOCKED_BROKER_TELEMETRY", "telemetry": acc_summary.get("telemetry")}
        bal = float(acc_summary.get("balance") or 0.0)
        if bal <= 0:
            return {"status": "BLOCKED_BROKER_TELEMETRY", "reason": "BROKER_BALANCE_UNAVAILABLE"}

        from app.services.market_feed_v2 import get_market_snapshot
        try:
            market_data = get_market_snapshot(sym, force_refresh=True)
        except Exception as exc:
            return {
                "status": "VETOED_BY_DATA_INTEGRITY",
                "reason": f"VETO_UNVERIFIED_MARKET_DATA:{exc}",
            }

        requested_entry = float(entry_price)
        broker_entry = float(market_data["price"])
        pip_size = float(market_data["pip_size"])
        max_deviation = pip_size * 20.0
        if abs(requested_entry - broker_entry) > max_deviation:
            return {
                "status": "VETOED_BY_PRICE_DEVIATION",
                "reason": (
                    f"VETO_CANDIDATE_PRICE_DEVIATION: proposed={requested_entry}, "
                    f"broker={broker_entry}, max={max_deviation}"
                ),
            }
        entry_price = broker_entry

        signal = SignalPayload(
            id=sig_id,
            symbol=sym,
            action=act,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            timeframe=timeframe,
            volume=0.01,
            account_id=str(acc_summary.get("account_id") or ""),
            source="BROKER_AUTHORITATIVE_AUTONOMOUS_SCANNER",
        )

        macro_data = economic_calendar_service.get_current_news_feed_bias()

        from app.services.broker_candle_feed import get_broker_multi_timeframe_candles
        from app.services.pretrade_intelligence_engine import pretrade_intelligence_engine
        try:
            candles = get_broker_multi_timeframe_candles(sym, count=60)
            spread_divisor = pip_size * 10.0 if "XAU" in sym else pip_size
            pretrade = pretrade_intelligence_engine.scan_market(
                symbol=sym,
                live_tick={
                    "bid": float(market_data["bid"]),
                    "ask": float(market_data["ask"]),
                    "spread": round(float(market_data["spread"]) / spread_divisor, 2),
                },
                timeframe_candles=candles,
            )
        except Exception as exc:
            return {"status": "VETOED_BY_DATA_INTEGRITY", "reason": f"BROKER_CANDLES_UNAVAILABLE:{exc}"}
        if not pretrade.get("trade_allowed", False):
            return {
                "status": "REJECTED_BY_PRETRADE",
                "reason": pretrade.get("decision_reason") or pretrade.get("reason"),
                "pretrade": pretrade,
            }
        required_action = str((pretrade.get("setup") or {}).get("direction", "")).upper()
        if required_action != act:
            return {
                "status": "REJECTED_BY_PRETRADE",
                "reason": "SIGNAL_DIRECTION_CONFLICT_WITH_PRETRADE",
                "pretrade": pretrade,
            }

        # 2. 6-AGENT CONSENSUS EVALUATION
        consensus_res_obj = consensus_engine.process_signal(
            signal=signal,
            market_data=market_data,
            macro_data=macro_data,
            account_status=acc_summary,
            save_to_db=True
        )

        consensus_result = consensus_res_obj.dict() if hasattr(consensus_res_obj, "dict") else dict(consensus_res_obj)
        decision_status = consensus_result.get("decision_status", "REJECTED")
        decision_score = consensus_result.get("decision_score", 0.0)

        # 3. DYNAMIC POSITION SIZING
        sizing = risk_engine.calculate_position_size(
            symbol=sym,
            account_equity=bal,
            entry_price=entry_price,
            stop_loss=stop_loss
        )
        recommended_volume = sizing.get("calculated_volume", 0.01)

        # If rejected by AI consensus, fail closed (NO TRADE)
        if decision_status != "APPROVED":
            return {
                "status": "REJECTED_BY_AI_CONSENSUS",
                "decision_score": decision_score,
                "consensus_result": consensus_result,
                "sizing": sizing,
                "message": consensus_result.get("full_analysis", "Setup did not achieve 6-agent consensus.")
            }

        # 4. LIVE SAFETY GATE EVALUATION
        is_safe, safety_msg, safety_telemetry = live_safety_gate.evaluate_order_safety(
            symbol=sym,
            action=act,
            volume=recommended_volume,
            entry_price=entry_price,
            sl_price=stop_loss,
            tp_price=take_profit,
            ignore_news_lockout=False,
            require_fresh_quotes=True
        )

        if not is_safe:
            return {
                "status": "VETOED_BY_SAFETY_GATE",
                "reason": safety_msg,
                "telemetry": safety_telemetry,
                "consensus_result": consensus_result
            }

        # 5. ORDER EXECUTION VIA CTRADER OPEN API
        exec_res = ctrader_execution_service.execute_market_order(
            symbol=sym,
            action=act,
            volume=recommended_volume,
            sl_price=stop_loss,
            tp_price=take_profit,
            comment=f"TradeTalk AI ({decision_score}%)",
            signal_id=consensus_result.get("signal_id"),
            ignore_news_lockout=False
        )

        # 5. POST-EXECUTION RECORDING
        return {
            "status": "SUCCESS" if exec_res.get("status") == "SUCCESS" else "EXECUTION_FAILED",
            "execution_result": exec_res,
            "decision_score": decision_score,
            "volume_executed": recommended_volume,
            "signal_id": consensus_result.get("signal_id"),
            "consensus_result": consensus_result,
            "safety_telemetry": safety_telemetry
        }

    def check_and_manage_open_positions(self, live_prices: Dict[str, float]) -> List[Dict[str, Any]]:
        """
        Autonomous trailing stop and Break-Even management for open positions.
        """
        positions = ctrader_execution_service.get_open_positions()
        updates = []

        for pos in positions:
            pos_id = pos.get("id")
            sym = pos.get("symbol", "XAUUSD")
            pos_type = pos.get("type", "BUY").upper()
            entry = float(pos.get("entry_price", 0.0))
            sl = float(pos.get("sl_price", 0.0))
            tp = float(pos.get("tp_price", 0.0))
            quote = ctrader_cloud_gateway.get_live_price(sym)
            if not quote:
                continue
            cur_p = quote["bid"] if pos_type == "BUY" else quote["ask"]

            if not entry or not sl:
                continue

            r_dist = abs(entry - sl)
            if r_dist <= 0:
                continue

            current_profit_dist = (cur_p - entry) if pos_type == "BUY" else (entry - cur_p)
            current_r_multiple = current_profit_dist / r_dist

            # Move to Break-Even Check
            if self.break_even_enabled and current_r_multiple >= self.be_threshold_r:
                if (pos_type == "BUY" and sl < entry) or (pos_type == "SELL" and sl > entry):
                    be_res = ctrader_execution_service.move_to_break_even(position_id=pos_id, buffer_pips=1.0)
                    updates.append({
                        "action": "MOVED_TO_BREAK_EVEN",
                        "position_id": pos_id,
                        "result": be_res
                    })

        return updates

    def get_status(self) -> Dict[str, Any]:
        """Returns autonomous trader operational status and parameters."""
        return {
            "is_running": self.is_running,
            "active_symbol": self.active_symbol,
            "trailing_enabled": self.trailing_enabled,
            "break_even_enabled": self.break_even_enabled,
            "be_threshold_r": self.be_threshold_r,
            "gateway_status": ctrader_cloud_gateway.get_gateway_status()
        }

autonomous_trader = AutonomousTrader()

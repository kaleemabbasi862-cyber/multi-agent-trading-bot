import uuid
import datetime
from fastapi import APIRouter, HTTPException
from app.database.models import SignalPayload, ConsensusResult
from app.database.db import db
from app.engine.consensus_engine import consensus_engine
from app.engine.execution_engine import execution_engine
from app.services.market_feed_v2 import get_gold_market_snapshot, get_market_snapshot
from app.services.economic_calendar import economic_calendar
import cbot_bridge
import settings_manager

router = APIRouter(prefix="/api", tags=["Signals"])

@router.get("/signals")
async def get_signals_history():
    return db.get_recent_signals(limit=50)

@router.get("/signals/pending")
@router.get("/pending")
@router.get("/pending-orders")
async def get_pending_signals_queue():
    """Returns currently pending approved orders for cBot on Account #5908018."""
    return cbot_bridge.get_pending_orders_for_cbot()

@router.get("/consensus")
async def get_live_consensus():
    """
    Returns live quantitative consensus data across all 7 agents for active instrument.
    """
    cur_sym = settings_manager.get_active_symbol()
    cur_lot = settings_manager.get_active_lot_size()
    market_data = get_market_snapshot(cur_sym, force_refresh=True)
    macro_data = economic_calendar.get_macro_status()
    acc_status = cbot_bridge.get_cbot_status()
    
    from app.services.volatility_engine import volatility_engine
    current_price = float(market_data.get("price") or market_data.get("bid") or 0.0)
    trend = market_data.get("indicators", {}).get("trend", market_data.get("trend_1h", "BULLISH"))
    act = "BUY" if trend == "BULLISH" else "SELL"

    vol_state = volatility_engine.get_symbol_volatility(cur_sym)
    sl_dist = vol_state.get("recommended_sl_distance", 6.0)
    tp_dist = round(sl_dist * 2.0, 5)

    sl = round(current_price - sl_dist, 5) if act == "BUY" else round(current_price + sl_dist, 5)
    tp = round(current_price + tp_dist, 5) if act == "BUY" else round(current_price - tp_dist, 5)

    sim_signal = SignalPayload(
        id=f"TELEMETRY_{uuid.uuid4().hex[:6].upper()}",
        symbol=cur_sym,
        action=act,
        entry_price=current_price,
        stop_loss=sl,
        take_profit=tp,
        volume=cur_lot,
        timeframe="15m & 1H",
        strategy_name=f"{cur_sym}_MultiAgent_Consensus_v2"
    )
    
    eval_acc = dict(acc_status) if isinstance(acc_status, dict) else {}
    eval_acc["open_positions"] = []  # Evaluate underlying market setup conviction for continuous dashboard telemetry
    
    consensus_res = consensus_engine.process_signal(
        signal=sim_signal,
        market_data=market_data,
        macro_data=macro_data,
        account_status=eval_acc,
        save_to_db=False
    )
    
    dec_map = {d.agent_name: d for d in consensus_res.agent_decisions}

    def _agent_payload(agent_id: str, display_name: str, key_name: str, weight_str: str, role_str: str) -> Dict[str, Any]:
        dec = dec_map.get(key_name)
        if dec is not None:
            is_active = (dec.decision != "FAIL" and not dec.metrics.get("unavailable", False))
            return {
                "id": agent_id,
                "name": display_name,
                "weight": weight_str,
                "role": role_str,
                "score": dec.score,
                "status": "Active" if is_active else "UNAVAILABLE",
                "decision": dec.decision,
                "reasoning": dec.reasoning_summary,
                "metrics": dec.metrics
            }
        else:
            return {
                "id": agent_id,
                "name": display_name,
                "weight": weight_str,
                "role": role_str,
                "score": 0.0,
                "status": "UNAVAILABLE",
                "decision": "UNAVAILABLE",
                "reasoning": f"{key_name} did not execute in this evaluation cycle.",
                "metrics": {"unavailable": True}
            }

    return {
        "status": "success",
        "market": market_data,
        "macro": macro_data,
        "account": acc_status,
        "consensus": consensus_res.dict() if hasattr(consensus_res, "dict") else consensus_res,
        "agents": [
            _agent_payload("agent_1", "Chart Sniper (Technical)", "Technical Analyst Agent", "25%", "15m & 1H EMAs, RSI 14, S/R Levels, Regime Classification"),
            _agent_payload("agent_2", "News Radar (Fundamental)", "Fundamental & Sentiment Agent", "18%", "CPI, NFP, FOMC High-Impact News Lockout"),
            _agent_payload("agent_3", "Shield Guard (Risk Veto)", "Risk Management Agent", "25% (Hard Veto)", "0.01 Lots Only, Min 1:2 R:R, -$5.00 Daily Circuit Breaker"),
            _agent_payload("agent_4", "SMC Hunter (Liquidity)", "Liquidity & SMC Agent", "18%", "Order Blocks, Liquidity Sweeps, Fair Value Gaps (FVG)"),
            _agent_payload("agent_5", "Quant Brain (Trade Quality)", "Trade Quality Agent", "18%", "Historical Pattern Expectancy & Edge Scoring"),
            {
                "id": "agent_6",
                "name": "The General (Head Desk)",
                "weight": "Executive Arbiter",
                "role": "Final Consensus Gatekeeper (>= Threshold + Zero Veto)",
                "score": consensus_res.decision_score,
                "status": consensus_res.decision_status,
                "decision": consensus_res.decision_status,
                "reasoning": consensus_res.full_analysis
            }
        ]
    }

@router.get("/signals/dna/{signal_id}")
@router.get("/signals/{signal_id}/dna")
async def get_signal_decision_dna(signal_id: str):
    dna = db.get_decision_dna(signal_id)
    if not dna:
        raise HTTPException(status_code=404, detail=f"Decision DNA not found for signal '{signal_id}'")
    return {
        "status": "SUCCESS",
        "signal_id": signal_id,
        "dna": dna
    }

@router.get("/signals/{signal_id}/explain")
async def get_signal_explanation(signal_id: str):
    dna = db.get_decision_dna(signal_id)
    if not dna:
        raise HTTPException(status_code=404, detail=f"Decision DNA explanation not found for signal '{signal_id}'")
    return {
        "status": "SUCCESS",
        "signal_id": signal_id,
        "explainability": dna.get("explainability", {}),
        "explanation": dna.get("explanation", ""),
        "decision_score": dna.get("decision_score", 0.0),
        "status": dna.get("status", "UNKNOWN")
    }


@router.post("/signals/simulate")
async def simulate_signal(signal: SignalPayload):
    """
    Simulates a signal through all 7 agents without executing a live order.
    """
    sym = signal.symbol or settings_manager.get_active_symbol()
    market_data = get_market_snapshot(sym, force_refresh=False)
    macro_data = economic_calendar.get_macro_status()
    acc_status = cbot_bridge.get_cbot_status()
    
    consensus_res = consensus_engine.process_signal(
        signal=signal,
        market_data=market_data,
        macro_data=macro_data,
        account_status=acc_status,
        save_to_db=False
    )
    return consensus_res

@router.post("/signals/execute")
async def execute_approved_signal(signal: SignalPayload):
    """
    Runs consensus engine and dispatches trade if approved.
    """
    sym = signal.symbol or settings_manager.get_active_symbol()
    market_data = get_market_snapshot(sym, force_refresh=True)
    macro_data = economic_calendar.get_macro_status()
    acc_status = cbot_bridge.get_cbot_status()
    
    consensus_res = consensus_engine.process_signal(
        signal=signal,
        market_data=market_data,
        macro_data=macro_data,
        account_status=acc_status,
        save_to_db=True
    )
    
    if consensus_res.decision_status == "APPROVED":
        exec_res = execution_engine.dispatch_trade(consensus_res, signal)
        consensus_res.execution_result = exec_res
        
    return consensus_res


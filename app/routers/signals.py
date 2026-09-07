import uuid
import datetime
from fastapi import APIRouter, HTTPException
from app.database.models import SignalPayload, ConsensusResult
from app.database.db import db
from app.engine.consensus_engine import consensus_engine
from app.engine.execution_engine import execution_engine
from app.services.market_feed_v2 import get_gold_market_snapshot
from app.services.economic_calendar import economic_calendar
import cbot_bridge

router = APIRouter(prefix="/api", tags=["Signals"])

@router.get("/signals")
async def get_signals_history():
    return db.get_recent_signals(limit=50)

@router.get("/signals/dna/{signal_id}")
async def get_signal_decision_dna(signal_id: str):
    dna = db.get_decision_dna(signal_id)
    if not dna:
        raise HTTPException(status_code=404, detail=f"Decision DNA not found for signal '{signal_id}'")
    return dna

@router.post("/signals/simulate")
async def simulate_signal(signal: SignalPayload):
    """
    Simulates a signal through all 7 agents without executing a live order.
    """
    market_data = get_gold_market_snapshot()
    macro_data = economic_calendar.get_macro_status()
    acc_status = cbot_bridge.get_cbot_status()
    
    consensus_res = consensus_engine.process_signal(
        signal=signal,
        market_data=market_data,
        macro_data=macro_data,
        account_status=acc_status
    )
    return consensus_res

@router.post("/signals/execute")
async def execute_approved_signal(signal: SignalPayload):
    """
    Runs consensus engine and dispatches trade if approved.
    """
    market_data = get_gold_market_snapshot()
    macro_data = economic_calendar.get_macro_status()
    acc_status = cbot_bridge.get_cbot_status()
    
    consensus_res = consensus_engine.process_signal(
        signal=signal,
        market_data=market_data,
        macro_data=macro_data,
        account_status=acc_status
    )
    
    if consensus_res.decision_status == "APPROVED":
        exec_res = execution_engine.dispatch_trade(consensus_res, signal)
        consensus_res.execution_result = exec_res
        
    return consensus_res

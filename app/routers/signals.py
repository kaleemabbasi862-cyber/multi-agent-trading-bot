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

@router.get("/consensus")
async def get_live_consensus():
    """
    Returns live quantitative consensus data across all 7 agents for Gold (XAUUSD).
    """
    market_data = get_gold_market_snapshot()
    macro_data = economic_calendar.get_macro_status()
    acc_status = cbot_bridge.get_cbot_status()
    
    current_price = market_data.get("price", 2750.0)
    sim_signal = SignalPayload(
        id=f"LIVE_SCAN_{uuid.uuid4().hex[:6].upper()}",
        symbol="XAUUSD",
        action="BUY" if market_data.get("trend_1h", "BULLISH") == "BULLISH" else "SELL",
        entry_price=current_price,
        stop_loss=round(current_price - 6.0 if market_data.get("trend_1h", "BULLISH") == "BULLISH" else current_price + 6.0, 2),
        take_profit=round(current_price + 12.0 if market_data.get("trend_1h", "BULLISH") == "BULLISH" else current_price - 12.0, 2),
        timeframe="15m",
        strategy_name="Gold_MultiAgent_SMC_v2"
    )
    
    consensus_res = consensus_engine.process_signal(
        signal=sim_signal,
        market_data=market_data,
        macro_data=macro_data,
        account_status=acc_status
    )
    
    return {
        "status": "success",
        "market": market_data,
        "macro": macro_data,
        "account": acc_status,
        "consensus": consensus_res,
        "agents": [
            {
                "id": "agent_1",
                "name": "Technical Agent",
                "weight": "20%",
                "role": "15m & 1H EMAs, RSI 14, S/R Levels",
                "score": consensus_res.agent_scores.get("Technical Analyst Agent", 85),
                "status": "Active",
                "decision": consensus_res.agent_decisions.get("Technical Analyst Agent", "PASS")
            },
            {
                "id": "agent_2",
                "name": "Fundamental Agent",
                "weight": "15%",
                "role": "CPI, NFP, FOMC High-Impact News Lockout",
                "score": consensus_res.agent_scores.get("Fundamental & Sentiment Agent", 90),
                "status": "Active",
                "decision": consensus_res.agent_decisions.get("Fundamental & Sentiment Agent", "PASS")
            },
            {
                "id": "agent_3",
                "name": "Risk Veto Agent",
                "weight": "20% (Hard Veto)",
                "role": "0.01 Lots Only, Min 1:2 R:R, -$5.00 Daily Circuit Breaker",
                "score": consensus_res.agent_scores.get("Risk Management Agent", 100),
                "status": "Active (VETO POWER)",
                "decision": consensus_res.agent_decisions.get("Risk Management Agent", "PASS")
            },
            {
                "id": "agent_4",
                "name": "Market Regime Agent",
                "weight": "15%",
                "role": "Trend vs Range Chop Identifier",
                "score": consensus_res.agent_scores.get("Market Regime Agent", 80),
                "status": "Active",
                "decision": consensus_res.agent_decisions.get("Market Regime Agent", "PASS")
            },
            {
                "id": "agent_5",
                "name": "Liquidity & SMC Agent",
                "weight": "15%",
                "role": "Order Blocks, Liquidity Sweeps, Fair Value Gaps (FVG)",
                "score": consensus_res.agent_scores.get("Liquidity & SMC Agent", 85),
                "status": "Active",
                "decision": consensus_res.agent_decisions.get("Liquidity & SMC Agent", "PASS")
            },
            {
                "id": "agent_6",
                "name": "Trade Quality Agent",
                "weight": "15%",
                "role": "Historical Pattern Expectancy & Edge Scoring",
                "score": consensus_res.agent_scores.get("Trade Quality Agent", 85),
                "status": "Active",
                "decision": consensus_res.agent_decisions.get("Trade Quality Agent", "PASS")
            },
            {
                "id": "agent_7",
                "name": "Head Desk Manager",
                "weight": "Executive Arbiter",
                "role": "Final Consensus Gatekeeper (>=85% Threshold + Zero Veto)",
                "score": consensus_res.decision_score,
                "status": consensus_res.decision_status,
                "decision": consensus_res.decision_status
            }
        ]
    }

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

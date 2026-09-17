import uuid
import datetime
from typing import Any, Dict, Tuple
from fastapi import APIRouter, HTTPException
from app.database.models import SignalPayload, ConsensusResult
from app.database.db import db
from app.engine.consensus_engine import consensus_engine
from app.engine.execution_engine import execution_engine
from app.services.market_feed_v2 import get_gold_market_snapshot, get_market_snapshot, get_multi_timeframe_candles
from app.services.pretrade_intelligence_engine import pretrade_intelligence_engine
from app.services.economic_calendar import economic_calendar
import cbot_bridge
import settings_manager

router = APIRouter(prefix="/api", tags=["Signals"])


def _authoritative_pretrade(symbol: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    market = get_market_snapshot(symbol, force_refresh=True)
    pip_size = float(market["pip_size"])
    spread = float(market["spread"])
    divisor = pip_size * 10.0 if "XAU" in symbol.upper() else pip_size
    spread_pips = round(spread / divisor, 2)
    candles = get_multi_timeframe_candles(symbol)
    scan = pretrade_intelligence_engine.scan_market(
        symbol=symbol.upper(),
        live_tick={
            "bid": float(market["bid"]),
            "ask": float(market["ask"]),
            "spread": spread_pips,
        },
        timeframe_candles=candles,
    )
    return market, scan


def _blocked_consensus_payload(
    symbol: str,
    market: Dict[str, Any],
    scan: Dict[str, Any],
    account: Dict[str, Any],
) -> Dict[str, Any]:
    reason = scan.get("decision_reason") or scan.get("reason") or "PRETRADE_GATE_CLOSED"
    quality = float((scan.get("quality_score") or {}).get("score", 0.0))
    mtf_score = float((scan.get("mtf") or {}).get("confluence_score", 0.0))
    blocked = {
        "signal_id": None,
        "symbol": symbol,
        "direction": (scan.get("setup") or {}).get("direction", "FLAT"),
        "decision_status": "REJECTED",
        "decision_score": 0.0,
        "pretrade_quality_score": quality,
        "agent_decisions": [],
        "risk_check": {"passed": False, "veto_reason": reason},
        "full_analysis": reason,
        "execution_result": None,
        "system_state": "PRETRADE_BLOCKED",
        "critical_agent_failures": ["PRETRADE_GATE"],
    }
    return {
        "status": "success",
        "market": market,
        "macro": economic_calendar.get_macro_status(),
        "account": account,
        "pretrade": scan,
        "consensus": blocked,
        "agents": [
            {"id": "agent_1", "name": "Chart Sniper (Technical)", "score": mtf_score,
             "status": "BLOCKED", "decision": "NO_TRADE", "reasoning": reason,
             "metrics": scan.get("mtf", {})},
            {"id": "agent_2", "name": "News Radar (Fundamental)", "score": 0.0,
             "status": "NOT_EVALUATED", "decision": "NO_TRADE", "reasoning": reason, "metrics": {}},
            {"id": "agent_3", "name": "Shield Guard (Risk Veto)", "score": 0.0,
             "status": "VETO", "decision": "FAIL", "reasoning": reason, "metrics": {}},
            {"id": "agent_4", "name": "SMC Hunter (Liquidity)", "score": 0.0,
             "status": "BLOCKED", "decision": "NO_TRADE", "reasoning": reason,
             "metrics": scan.get("smc", {})},
            {"id": "agent_5", "name": "Quant Brain (Trade Quality)", "score": quality,
             "status": "BLOCKED", "decision": "NO_TRADE", "reasoning": reason,
             "metrics": scan.get("quality_score", {})},
            {"id": "agent_6", "name": "The General (Head Desk)", "score": 0.0,
             "status": "REJECTED", "decision": "REJECTED", "reasoning": reason},
        ],
    }

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
    """Return one broker-authoritative decision shared with the pre-trade gate."""
    cur_sym = settings_manager.get_active_symbol()
    cur_lot = settings_manager.get_active_lot_size()
    acc_status = cbot_bridge.get_cbot_status()
    try:
        market_data, scan = _authoritative_pretrade(cur_sym)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"BROKER_DATA_UNAVAILABLE:{exc}") from exc

    if not scan.get("trade_allowed", False):
        return _blocked_consensus_payload(cur_sym, market_data, scan, acc_status)

    setup = scan.get("setup") or {}
    act = str(setup.get("direction", "")).upper()
    if act not in ("BUY", "SELL"):
        return _blocked_consensus_payload(cur_sym, market_data, scan, acc_status)

    current_price = float(market_data["price"])
    atr = float((scan.get("indicators") or {}).get("atr") or 0.0)
    if atr <= 0:
        raise HTTPException(status_code=503, detail="BROKER_ATR_UNAVAILABLE")
    sl_dist = max(atr * 0.5, 3.5 if "XAU" in cur_sym else atr * 0.5)
    sl = round(current_price - sl_dist, 5) if act == "BUY" else round(current_price + sl_dist, 5)
    tp = round(current_price + sl_dist * 2.0, 5) if act == "BUY" else round(current_price - sl_dist * 2.0, 5)

    signal = SignalPayload(
        id=f"TELEMETRY_{uuid.uuid4().hex[:6].upper()}",
        symbol=cur_sym,
        action=act,
        entry_price=current_price,
        stop_loss=sl,
        take_profit=tp,
        volume=cur_lot,
        timeframe="M15_H1",
        strategy_name=f"{cur_sym}_Broker_Authoritative_Consensus",
    )
    consensus_res = consensus_engine.process_signal(
        signal=signal,
        market_data=market_data,
        macro_data=economic_calendar.get_macro_status(),
        account_status=acc_status,
        save_to_db=False,
    )
    dec_map = {d.agent_name: d for d in consensus_res.agent_decisions}

    def agent_payload(agent_id: str, display_name: str, key_name: str) -> Dict[str, Any]:
        dec = dec_map.get(key_name)
        if dec is None:
            return {"id": agent_id, "name": display_name, "score": 0.0,
                    "status": "UNAVAILABLE", "decision": "UNAVAILABLE",
                    "reasoning": f"{key_name} unavailable.", "metrics": {}}
        return {"id": agent_id, "name": display_name, "score": dec.score,
                "status": "ACTIVE" if dec.decision != "FAIL" else "VETO",
                "decision": dec.decision, "reasoning": dec.reasoning_summary,
                "metrics": dec.metrics}

    return {
        "status": "success",
        "market": market_data,
        "macro": economic_calendar.get_macro_status(),
        "account": acc_status,
        "pretrade": scan,
        "consensus": consensus_res.dict() if hasattr(consensus_res, "dict") else consensus_res,
        "agents": [
            agent_payload("agent_1", "Chart Sniper (Technical)", "Technical Analyst Agent"),
            agent_payload("agent_2", "News Radar (Fundamental)", "Fundamental & Sentiment Agent"),
            agent_payload("agent_3", "Shield Guard (Risk Veto)", "Risk Management Agent"),
            agent_payload("agent_4", "SMC Hunter (Liquidity)", "Liquidity & SMC Agent"),
            agent_payload("agent_5", "Quant Brain (Trade Quality)", "Trade Quality Agent"),
            {"id": "agent_6", "name": "The General (Head Desk)",
             "score": consensus_res.decision_score, "status": consensus_res.decision_status,
             "decision": consensus_res.decision_status, "reasoning": consensus_res.full_analysis},
        ],
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


def _verified_signal(signal: SignalPayload, market: Dict[str, Any], scan: Dict[str, Any]) -> SignalPayload:
    if not scan.get("trade_allowed", False):
        reason = scan.get("decision_reason") or scan.get("reason") or "PRETRADE_GATE_CLOSED"
        raise HTTPException(status_code=409, detail=reason)
    required_action = str((scan.get("setup") or {}).get("direction", "")).upper()
    if required_action not in ("BUY", "SELL") or signal.action.upper() != required_action:
        raise HTTPException(status_code=409, detail="SIGNAL_DIRECTION_CONFLICT_WITH_PRETRADE")
    return signal.copy(update={
        "symbol": market["symbol"],
        "entry_price": float(market["price"]),
        "source": "BROKER_AUTHORITATIVE",
    })


@router.post("/signals/simulate")
async def simulate_signal(signal: SignalPayload):
    """Evaluate a broker-verified setup without any execution side effect."""
    sym = signal.symbol or settings_manager.get_active_symbol()
    try:
        market_data, scan = _authoritative_pretrade(sym)
        verified = _verified_signal(signal, market_data, scan)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"BROKER_DATA_UNAVAILABLE:{exc}") from exc
    return consensus_engine.process_signal(
        signal=verified,
        market_data=market_data,
        macro_data=economic_calendar.get_macro_status(),
        account_status=cbot_bridge.get_cbot_status(),
        save_to_db=False,
    )


@router.post("/signals/execute")
async def execute_approved_signal(signal: SignalPayload):
    """Dispatch only an auto-trade-enabled, broker-verified, pre-trade-approved signal."""
    if not settings_manager.load_settings().get("auto_trade_enabled", False):
        raise HTTPException(status_code=409, detail="AUTO_TRADE_DISABLED")
    sym = signal.symbol or settings_manager.get_active_symbol()
    try:
        market_data, scan = _authoritative_pretrade(sym)
        verified = _verified_signal(signal, market_data, scan)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"BROKER_DATA_UNAVAILABLE:{exc}") from exc

    consensus_res = consensus_engine.process_signal(
        signal=verified,
        market_data=market_data,
        macro_data=economic_calendar.get_macro_status(),
        account_status=cbot_bridge.get_cbot_status(),
        save_to_db=True,
    )
    if consensus_res.decision_status == "APPROVED":
        exec_res = execution_engine.dispatch_trade(consensus_res, verified)
        consensus_res.execution_result = exec_res
    return consensus_res


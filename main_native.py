import os
import sys
import asyncio
import uuid
import datetime
import traceback
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()

# TradeTalk V2 Modules
from app.config import settings
from app.database.models import SignalPayload
from app.database.db import db
from app.engine.consensus_engine import consensus_engine
from app.engine.execution_engine import execution_engine
from app.services.market_feed_v2 import get_market_snapshot, get_gold_market_snapshot
from app.services.economic_calendar import economic_calendar
from app.services.webhook_security import webhook_security
import cbot_bridge
import settings_manager
import copilot_agent

# Initialize FastAPI App
app = FastAPI(
    title="TradeTalk AI V2 - Autonomous Multi-Agent Trading System",
    version=settings.VERSION
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Modular V2 Routers
from app.routers import market, signals, trading, backtest, cbot, system

app.include_router(market.router)
app.include_router(signals.router)
app.include_router(trading.router)
app.include_router(backtest.router)
app.include_router(cbot.router)
app.include_router(system.router)

# -------------------------------------------------------------
# Webhook Gateway (TradingView with HMAC & Replay Security)
# -------------------------------------------------------------
@app.post("/webhook/tradingview")
async def receive_tradingview_webhook(
    request: Request,
    x_tradetalk_signature: str = Header(None),
    x_tradetalk_token: str = Header(None),
    x_tradetalk_timestamp: str = Header(None)
):
    """
    Ingests TradingView alerts and runs through 7-Agent Consensus & Risk Veto Gate.
    """
    raw_body = await request.body()
    try:
        payload_json = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Security Verification
    token = x_tradetalk_token or payload_json.get("token") or payload_json.get("secret")
    is_valid, sec_err = webhook_security.verify_request(
        raw_body=raw_body,
        signature=x_tradetalk_signature,
        token=token,
        timestamp_header=x_tradetalk_timestamp
    )
    if not is_valid:
        db.log_audit(
            event_type="WEBHOOK_SECURITY_REJECT",
            actor="TradingViewWebhook",
            details=f"Security verification failed: {sec_err}"
        )
        raise HTTPException(status_code=401, detail=sec_err)

    # Normalize Payload
    symbol = payload_json.get("symbol", settings_manager.get_active_symbol())
    action = payload_json.get("action") or payload_json.get("signal") or "BUY"
    action = action.upper()
    entry = float(payload_json.get("entry_price") or payload_json.get("price") or 2750.0)
    sl = float(payload_json.get("stop_loss") or payload_json.get("sl") or (entry - 6.0 if action == "BUY" else entry + 6.0))
    tp = float(payload_json.get("take_profit") or payload_json.get("tp") or (entry + 12.0 if action == "BUY" else entry - 12.0))
    tf = payload_json.get("timeframe", "15m")
    strat = payload_json.get("strategy_name", "TradingView_Webhook_v2")
    vol = float(payload_json.get("volume") or payload_json.get("lot_size") or settings_manager.get_active_lot_size())

    sig_model = SignalPayload(
        id=payload_json.get("id") or f"TV_{uuid.uuid4().hex[:8].upper()}",
        symbol=symbol,
        action=action,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        volume=vol,
        timeframe=tf,
        strategy_name=strat,
        source="TRADINGVIEW_WEBHOOK"
    )

    market_data = get_market_snapshot(symbol)
    macro_data = economic_calendar.get_macro_status()
    acc_status = cbot_bridge.get_cbot_status()

    # Process through 7 Agents + Guardian
    consensus_res = consensus_engine.process_signal(
        signal=sig_model,
        market_data=market_data,
        macro_data=macro_data,
        account_status=acc_status
    )

    # Dispatch to Paper, Demo, or Live Execution
    if consensus_res.decision_status == "APPROVED":
        exec_res = execution_engine.dispatch_trade(consensus_res, sig_model)
        consensus_res.execution_result = exec_res

    return {
        "status": consensus_res.decision_status,
        "score": consensus_res.decision_score,
        "signal_id": consensus_res.signal_id,
        "symbol": consensus_res.symbol,
        "action": consensus_res.direction,
        "analysis": consensus_res.full_analysis,
        "execution": consensus_res.execution_result
    }

# -------------------------------------------------------------
# Copilot & Autonomous Scanner Endpoints
# -------------------------------------------------------------
class CopilotChatRequest(BaseModel):
    message: str

class SettingsUpdateRequest(BaseModel):
    active_symbol: Optional[str] = None
    active_lot_size: Optional[float] = None
    min_confidence_threshold: Optional[float] = None
    auto_trade_enabled: Optional[bool] = None

@app.post("/api/copilot/chat")
async def chat_copilot(req: CopilotChatRequest):
    sys_state = {
        "auto_trade_enabled": settings_manager.load_settings().get("auto_trade_enabled", True),
        "trading_mode": execution_engine.mode,
        "active_pairs": settings_manager.get_active_pairs(),
        "active_symbol": settings_manager.get_active_symbol(),
        "active_lot_size": settings_manager.get_active_lot_size(),
        "min_confidence_threshold": settings_manager.get_min_confidence_threshold()
    }
    return copilot_agent.execute_copilot_intent(req.message, sys_state)

@app.post("/api/scan-now")
async def trigger_manual_scan():
    """Triggers immediate market scan on active symbol."""
    cur_settings = settings_manager.load_settings()
    cur_sym = cur_settings.get("active_symbol", "XAUUSD")
    cur_lot = cur_settings.get("active_lot_size", 0.01)

    market_data = get_market_snapshot(cur_sym, force_refresh=True)
    p = market_data["price"]
    pip = market_data.get("pip_size", 0.01)
    trend = market_data["indicators"]["trend"]
    act = "BUY" if trend == "BULLISH" else "SELL"

    if "XAU" in cur_sym or "GOLD" in cur_sym:
        sl_dist = 6.0
        tp_dist = 12.0
    elif "XAG" in cur_sym or "SILVER" in cur_sym:
        sl_dist = 0.35
        tp_dist = 0.75
    elif "JPY" in cur_sym:
        sl_dist = 0.40
        tp_dist = 0.85
    else:
        sl_dist = 0.0035
        tp_dist = 0.0075

    sl = round(p - sl_dist, 5) if act == "BUY" else round(p + sl_dist, 5)
    tp = round(p + tp_dist, 5) if act == "BUY" else round(p - tp_dist, 5)

    sig = SignalPayload(
        symbol=cur_sym,
        action=act,
        entry_price=p,
        stop_loss=sl,
        take_profit=tp,
        volume=cur_lot,
        timeframe="15m & 1H",
        strategy_name=f"{cur_sym}_Autonomous_Scan",
        source="MARKET_SCANNER"
    )

    macro_data = economic_calendar.get_macro_status()
    acc_status = cbot_bridge.get_cbot_status()

    consensus_res = consensus_engine.process_signal(
        signal=sig,
        market_data=market_data,
        macro_data=macro_data,
        account_status=acc_status
    )

    if consensus_res.decision_status == "APPROVED" and cur_settings.get("auto_trade_enabled", True):
        exec_res = execution_engine.dispatch_trade(consensus_res, sig)
        consensus_res.execution_result = exec_res

    return consensus_res

@app.get("/api/pairs/settings")
@app.get("/api/settings")
async def get_pairs_settings():
    s = settings_manager.load_settings()
    return {
        "all_pairs": settings_manager.ALL_SUPPORTED_PAIRS,
        "active_symbol": s.get("active_symbol", "XAUUSD"),
        "active_pairs": s.get("active_pairs", ["XAUUSD"]),
        "active_lot_size": s.get("active_lot_size", 0.01),
        "fixed_lot_size": s.get("active_lot_size", 0.01),
        "min_confidence_threshold": s.get("min_confidence_threshold", 75.0),
        "auto_trade_enabled": s.get("auto_trade_enabled", True),
        "trading_mode": execution_engine.mode
    }

@app.post("/api/settings/update")
@app.post("/api/pairs/settings")
async def update_settings(req: SettingsUpdateRequest):
    if req.active_symbol:
        settings_manager.set_active_symbol(req.active_symbol)
    if req.active_lot_size is not None:
        settings_manager.set_active_lot_size(req.active_lot_size)
    if req.min_confidence_threshold is not None:
        settings_manager.set_min_confidence_threshold(req.min_confidence_threshold)
    if req.auto_trade_enabled is not None:
        s = settings_manager.load_settings()
        s["auto_trade_enabled"] = bool(req.auto_trade_enabled)
        settings_manager.save_settings(s)

    updated = settings_manager.load_settings()
    return {
        "status": "SUCCESS",
        "active_symbol": updated.get("active_symbol", "XAUUSD"),
        "active_lot_size": updated.get("active_lot_size", 0.01),
        "min_confidence_threshold": updated.get("min_confidence_threshold", 75.0),
        "auto_trade_enabled": updated.get("auto_trade_enabled", True),
        "message": f"Settings updated: {updated.get('active_symbol')} @ {updated.get('active_lot_size')} Lots | Gate: {updated.get('min_confidence_threshold')}%"
    }

# -------------------------------------------------------------
# Frontend Dashboard View & Health
# -------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    html_path = Path(__file__).resolve().parent / "templates" / "dashboard.html"
    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
        "X-TradeTalk-Version": "2.0.0-7agents"
    }
    if html_path.exists():
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read(), headers=headers)
    return HTMLResponse(content="<h1>TradeTalk AI Dashboard</h1>", headers=headers)

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main_native:app", host="0.0.0.0", port=port, reload=True)

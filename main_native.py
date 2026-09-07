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
from app.services.market_feed_v2 import get_gold_market_snapshot
from app.services.economic_calendar import economic_calendar
from app.services.webhook_security import webhook_security
import cbot_bridge
import settings_manager
import copilot_agent

# Initialize FastAPI App
app = FastAPI(
    title="TradeTalk AI V2 - Autonomous Multi-Agent Gold Trading System",
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
    symbol = payload_json.get("symbol", "XAUUSD")
    action = payload_json.get("action") or payload_json.get("signal") or "BUY"
    action = action.upper()
    entry = float(payload_json.get("entry_price") or payload_json.get("price") or 2750.0)
    sl = float(payload_json.get("stop_loss") or payload_json.get("sl") or (entry - 6.0 if action == "BUY" else entry + 6.0))
    tp = float(payload_json.get("take_profit") or payload_json.get("tp") or (entry + 12.0 if action == "BUY" else entry - 12.0))
    tf = payload_json.get("timeframe", "15m")
    strat = payload_json.get("strategy_name", "TradingView_Webhook_v2")

    sig_model = SignalPayload(
        id=payload_json.get("id") or f"TV_{uuid.uuid4().hex[:8].upper()}",
        symbol=symbol,
        action=action,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        timeframe=tf,
        strategy_name=strat,
        source="TRADINGVIEW_WEBHOOK"
    )

    market_data = get_gold_market_snapshot()
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

@app.post("/api/copilot/chat")
async def chat_copilot(req: CopilotChatRequest):
    sys_state = {
        "auto_trade_enabled": settings_manager.load_settings().get("auto_trade_enabled", True),
        "trading_mode": execution_engine.mode,
        "active_pairs": ["XAUUSD"]
    }
    return copilot_agent.execute_copilot_intent(req.message, sys_state)

@app.post("/api/scan-now")
async def trigger_manual_scan():
    """Triggers immediate market scan on XAUUSD Gold."""
    market_data = get_gold_market_snapshot(force_refresh=True)
    p = market_data["price"]
    trend = market_data["indicators"]["trend"]
    act = "BUY" if trend == "BULLISH" else "SELL"
    sl = p - 6.0 if act == "BUY" else p + 6.0
    tp = p + 12.0 if act == "BUY" else p - 12.0

    sig = SignalPayload(
        symbol="XAUUSD",
        action=act,
        entry_price=p,
        stop_loss=sl,
        take_profit=tp,
        timeframe="15m & 1H",
        strategy_name="GoldSniper_Autonomous_Scan",
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

    if consensus_res.decision_status == "APPROVED" and settings_manager.load_settings().get("auto_trade_enabled", True):
        exec_res = execution_engine.dispatch_trade(consensus_res, sig)
        consensus_res.execution_result = exec_res

    return consensus_res

@app.get("/api/pairs/settings")
async def get_pairs_settings():
    return {
        "all_pairs": [{"symbol": "XAUUSD", "name": "Gold / USD", "category": "Metals", "icon": "fa-coins"}],
        "active_pairs": ["XAUUSD"],
        "auto_trade_enabled": settings_manager.load_settings().get("auto_trade_enabled", True),
        "trading_mode": execution_engine.mode
    }

@app.post("/api/pairs/settings")
async def update_pairs_settings():
    return {
        "active_pairs": ["XAUUSD"],
        "message": "System is locked strictly to Gold (XAUUSD) Sniper Mode"
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

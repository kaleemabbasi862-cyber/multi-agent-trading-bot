import os
import sys
import asyncio
import uuid
import datetime
import traceback
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
import uvicorn
import market_feed
import mt5_executor
import ctrader_executor
import cbot_bridge

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# -------------------------------------------------------------
# 1. API اور سسٹم کنفیگریشن
# -------------------------------------------------------------
load_dotenv()

def get_llm():
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
    if not api_key:
        api_key = "placeholder"
    
    primary = ChatGoogleGenerativeAI(
        model="gemini-3.5-flash",
        google_api_key=api_key,
        temperature=0.2
    )
    fallback_lite = ChatGoogleGenerativeAI(
        model="gemini-3.5-flash-lite",
        google_api_key=api_key,
        temperature=0.2
    )
    fallback_flash = ChatGoogleGenerativeAI(
        model="gemini-3.6-flash",
        google_api_key=api_key,
        temperature=0.2
    )
    
    return primary.with_fallbacks([fallback_lite, fallback_flash])

app = FastAPI(title="TradeTalk AI - Autonomous Multi-Agent Trading System")

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------
# 2. سسٹم اسٹیٹ اور سگنل ہسٹری (State & History Store)
# -------------------------------------------------------------
SYSTEM_STATE = {
    "auto_trade_enabled": True,
    "scanner_active": True,
    "paper_balance": 10000.00,
    "equity": 10000.00,
    "last_scan_time": None,
    "total_scans": 0,
    "total_executed": 0
}

SIGNALS_HISTORY = [
    {
        "id": "ORD-1082",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "symbol": "XAUUSD",
        "action": "BUY",
        "entry_price": 2748.50,
        "stop_loss": 2736.50,
        "take_profit": 2773.50,
        "timeframe": "15m",
        "strategy_name": "Autonomous_Market_Scanner",
        "decision_status": "APPROVED",
        "lot_size": 0.25,
        "tech_report": "گولڈ 15m پر EMA 50 کے اوپر ٹریڈ کر رہا ہے اور RSI 54 ہے جو کہ پُراعتماد بلش مومینٹم کی علامت ہے۔ R:R ریشو 1:2.08 ہے۔",
        "news_report": "مارکیٹ میں ڈالر کے خلاف محفوظ سرمایہ کاری (Safe Haven) کا رجحان قائم ہے۔ فی الحال کوئی فوری ہائی امپیکٹ نیوز خطرہ نہیں ہے۔",
        "risk_report": "$10,000 بیلنس پر 1% رسک ($100) کے مطابق 12 ڈالر SL کے لیے درست لاٹ سائز 0.25 Lots ہے۔",
        "final_decision": "[DECISION: APPROVED] - تمام ٹیکنیکل، فنڈامنٹل اور رسک شرائط مکمل ہیں۔ 0.25 Lots کی BUY ٹریڈ منظور کی جاتی ہے۔",
        "analysis": "1. Technical Analysis:\nگولڈ 15m پر EMA 50 کے اوپر ٹریڈ کر رہا ہے اور RSI 54 ہے جو کہ پُراعتماد بلش مومینٹم کی علامت ہے۔ R:R ریشو 1:2.08 ہے۔\n\n2. News Analysis:\nمارکیٹ میں ڈالر کے خلاف محفوظ سرمایہ کاری (Safe Haven) کا رجحان قائم ہے۔ فی الحال کوئی فوری ہائی امپیکٹ نیوز خطرہ نہیں ہے۔\n\n3. Risk Assessment:\n$10,000 بیلنس پر 1% رسک ($100) کے مطابق 12 ڈالر SL کے لیے درست لاٹ سائز 0.25 Lots ہے۔\n\n4. Final Desk Decision:\n[DECISION: APPROVED] - تمام ٹیکنیکل، فنڈامنٹل اور رسک شرائط مکمل ہیں۔ 0.25 Lots کی BUY ٹریڈ منظور کی جاتی ہے۔",
        "ctrader": {"status": "EXECUTED", "order_id": "MT5_TICKET_98412", "fill_price": 2748.50, "lot_size": 0.25}
    }
]

# -------------------------------------------------------------
# 3. ڈیٹا ماڈلز
# -------------------------------------------------------------
class TradingViewSignal(BaseModel):
    symbol: str              # e.g., "EURUSD" or "XAUUSD"
    action: str              # e.g., "BUY" or "SELL"
    entry_price: float       # e.g., 1.0850
    stop_loss: float         # e.g., 1.0820
    take_profit: float       # e.g., 1.0920
    timeframe: str           # e.g., "15m"
    strategy_name: str       # e.g., "Trend_Crossover_v1"

# -------------------------------------------------------------
# 4. ایگزیکیوشن انجن (cTrader cBot Bridge & Open API Execution Engine)
# -------------------------------------------------------------
def execute_order(symbol: str, action: str, lot_size: float, sl: float, tp: float, fill_price: float):
    # 1. Queue order for direct cBot execution in cTrader
    sig_id = f"ORD_{random_digits(5)}"
    cbot_bridge.queue_trade_for_cbot(symbol, action, lot_size, sl, tp, sig_id)

    # 2. Execute via cTrader Open API if active
    res = ctrader_executor.execute_ctrader_trade(
        symbol=symbol,
        action=action,
        lot_size=lot_size,
        sl_price=sl,
        tp_price=tp,
        comment="TradeTalk.AI Consensus"
    )
    res["cbot_queued"] = True
    SYSTEM_STATE["total_executed"] += 1
    return res

def random_digits(n=5):
    import random
    return "".join([str(random.randint(0, 9)) for _ in range(n)])

def send_telegram_alert(message: str):
    print(f"\n[Telegram Notification Sent]:\n{message}")

def extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                texts.append(item["text"])
            elif isinstance(item, str):
                texts.append(item)
            else:
                texts.append(str(item))
        return "\n".join(texts)
    return str(content)

# -------------------------------------------------------------
# 5. ملٹی ایجنٹ متوازی پائپ لائن
# -------------------------------------------------------------
async def run_forex_agents(signal: TradingViewSignal) -> dict:
    llm = get_llm()

    # ایجنٹ 1: ٹیکنیکل اینالسٹ
    tech_prompt = ChatPromptTemplate.from_messages([
        ("system", "آپ 10 سال کے تجربہ کار فاریکس ٹیکنیکل اینالسٹ ہیں۔ آپ کا کام مارکیٹ انڈیکیٹرز، سگنل، ٹرینڈ اور پرائس ایکشن کی درستی کی توثیق کرنا اور کوالٹی سکور (1-100) دینا ہے۔"),
        ("human", "سگنل کی جانچ کریں: Pair: {symbol}, Action: {action}, Entry: {entry}, SL: {sl}, TP: {tp}, TF: {tf}, Strategy: {strategy}")
    ])
    tech_chain = tech_prompt | llm

    # ایجنٹ 2: فنڈامنٹل اور نیوز اینالسٹ
    news_prompt = ChatPromptTemplate.from_messages([
        ("system", "آپ فاریکس فنڈامنٹل اینالسٹ ہیں۔ آپ مائیکرو فنڈامنٹل صورتحال اور نیوز رسک اسٹیٹس (LOW / MEDIUM / HIGH) کی جانچ کرتے ہیں۔"),
        ("human", "کرنسی پیئر {symbol} کے لیے نیوز رسک کا جائزہ لیں اور کلیئرنس رپورٹ دیں۔")
    ])
    news_chain = news_prompt | llm

    # ایجنٹ 3: رسک مینیجر
    risk_prompt = ChatPromptTemplate.from_messages([
        ("system", "آپ فاریکس رسک اینڈ منی مینیجر ہیں۔ اکاؤنٹ بیلنس $10,000 فرض کرتے ہوئے 1 فیصد رسک پر لاٹ سائز اور Risk-to-Reward تناسب کا تعین کریں۔"),
        ("human", "Entry: {entry}, SL: {sl}, Pair: {symbol} کے لیے لاٹ سائز اور R:R نکالیں۔")
    ])
    risk_chain = risk_prompt | llm

    # 1, 2 اور 3 ایجنٹس کو متوازی (Parallel) چلائیں تاکہ رسپانس تیز ترین ہو
    async def get_tech():
        raw = (await tech_chain.ainvoke({
            "symbol": signal.symbol, "action": signal.action, "entry": signal.entry_price,
            "sl": signal.stop_loss, "tp": signal.take_profit, "tf": signal.timeframe,
            "strategy": signal.strategy_name
        })).content
        return extract_text(raw)

    async def get_news():
        raw = (await news_chain.ainvoke({"symbol": signal.symbol})).content
        return extract_text(raw)

    async def get_risk():
        raw = (await risk_chain.ainvoke({
            "symbol": signal.symbol, "entry": signal.entry_price, "sl": signal.stop_loss
        })).content
        return extract_text(raw)

    tech_report, news_report, risk_report = await asyncio.gather(
        get_tech(), get_news(), get_risk()
    )

    # ایجنٹ 4: چیف مینیجر (تینوں رپورٹس کی بنیاد پر حتمی فیصلہ)
    manager_prompt = ChatPromptTemplate.from_messages([
        ("system", "آپ ٹریڈنگ ڈیسک کے ہیڈ ہیں۔ تمام ایجنٹس کی رپورٹس دیکھ کر حتمی فیصلہ [DECISION: APPROVED] یا [DECISION: REJECTED] دیں اور لاٹ سائز واضح کریں۔"),
        ("human", "ٹیکنیکل رپورٹ:\n{tech}\n\nنیوز رپورٹ:\n{news}\n\nرسک رپورٹ:\n{risk}\n\nحتمی فیصلہ دیں:")
    ])
    manager_chain = manager_prompt | llm
    manager_raw = (await manager_chain.ainvoke({
        "tech": tech_report, "news": news_report, "risk": risk_report
    })).content
    final_decision = extract_text(manager_raw)

    decision_status = "APPROVED" if "APPROVED" in final_decision.upper() else "REJECTED"

    full_analysis = (
        f"**1. Technical Analysis:**\n{tech_report}\n\n"
        f"**2. News Analysis:**\n{news_report}\n\n"
        f"**3. Risk Assessment:**\n{risk_report}\n\n"
        f"**4. Final Desk Decision:**\n{final_decision}"
    )

    return {
        "tech_report": tech_report,
        "news_report": news_report,
        "risk_report": risk_report,
        "final_decision": final_decision,
        "decision_status": decision_status,
        "full_analysis": full_analysis
    }

# -------------------------------------------------------------
# 6. خودکار مارکیٹ اسکینر پائپ لائن (Autonomous Market Scanner)
# -------------------------------------------------------------
async def scan_single_market(symbol: str, meta: dict):
    p = meta["price"]
    ind = meta["indicators"]
    rsi = ind["rsi"]
    trend = ind["trend"]

    # Calculate smart setup parameters
    action = "BUY" if (trend == "BULLISH" and rsi >= 48) else "SELL"
    sl_offset = 12.0 if "XAU" in symbol else (p * 0.003)
    tp_offset = 25.0 if "XAU" in symbol else (p * 0.007)

    sl = round(p - sl_offset if action == "BUY" else p + sl_offset, 2 if "XAU" in symbol or "BTC" in symbol else 4)
    tp = round(p + tp_offset if action == "BUY" else p - tp_offset, 2 if "XAU" in symbol or "BTC" in symbol else 4)

    signal = TradingViewSignal(
        symbol=symbol,
        action=action,
        entry_price=p,
        stop_loss=sl,
        take_profit=tp,
        timeframe="15m",
        strategy_name=f"Autonomous_AI_Scanner (RSI:{rsi:.0f})"
    )

    signal_id = str(uuid.uuid4())[:8]
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    agent_data = await run_forex_agents(signal)
    full_analysis = agent_data["full_analysis"]
    decision_status = agent_data["decision_status"]

    execution_result = None
    if decision_status == "APPROVED" and SYSTEM_STATE["auto_trade_enabled"]:
        lot_size = 0.25 if "XAU" in symbol else 0.10
        execution_result = execute_order(
            symbol=symbol,
            action=action,
            lot_size=lot_size,
            sl=sl,
            tp=tp,
            fill_price=p
        )

    record = {
        "id": signal_id,
        "timestamp": timestamp,
        "symbol": symbol,
        "action": action,
        "entry_price": p,
        "stop_loss": sl,
        "take_profit": tp,
        "timeframe": "15m",
        "strategy_name": signal.strategy_name,
        "decision_status": decision_status,
        "tech_report": agent_data["tech_report"],
        "news_report": agent_data["news_report"],
        "risk_report": agent_data["risk_report"],
        "final_decision": agent_data["final_decision"],
        "analysis": full_analysis,
        "ctrader": execution_result
    }

    SIGNALS_HISTORY.insert(0, record)
    if len(SIGNALS_HISTORY) > 25:
        SIGNALS_HISTORY.pop()

    return record

async def autonomous_scanner_background_loop():
    """Background worker that continuously evaluates live market data."""
    print("[*] Autonomous AI Market Scanner background task started.")
    await asyncio.sleep(10)  # Initial warmup
    
    symbols_cycle = ["XAUUSD", "EURUSD", "GBPUSD", "BTCUSD"]
    idx = 0

    while True:
        try:
            if SYSTEM_STATE["scanner_active"]:
                market_data = market_feed.get_live_market_data()
                target_sym = symbols_cycle[idx % len(symbols_cycle)]
                idx += 1

                if target_sym in market_data:
                    SYSTEM_STATE["last_scan_time"] = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")
                    SYSTEM_STATE["total_scans"] += 1
                    print(f"\n[{SYSTEM_STATE['last_scan_time']}] [AUTONOMOUS SCAN] Inspecting {target_sym}...")
                    await scan_single_market(target_sym, market_data[target_sym])

        except Exception as e:
            print(f"[!] Autonomous scanner cycle error: {e}")

        # Interval between automated market scans (60 seconds)
        await asyncio.sleep(60)

# -------------------------------------------------------------
# 7. FastAPI لائف سائیکل اور روٹس
# -------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(autonomous_scanner_background_loop())

@app.get("/api/market-prices")
@app.get("/api/live-prices")
def get_market_prices():
    return market_feed.get_live_market_data()

@app.get("/api/system-state")
def get_system_state():
    return SYSTEM_STATE

class MT5ConnectRequest(BaseModel):
    login: int
    password: str
    server: str
    path: str = None

class CTraderConnectRequest(BaseModel):
    account_id: str = "1005621"
    access_token: str = None
    client_id: str = None
    client_secret: str = None
    environment: str = "Live"

from fastapi import Request
from fastapi.responses import RedirectResponse

@app.get("/api/ctrader/status")
def get_ctrader_status():
    return ctrader_executor.get_ctrader_status()

@app.get("/api/ctrader/auth-url")
def get_ctrader_auth_url(request: Request):
    # Dynamic redirect URI pointing to callback endpoint
    host = request.headers.get("host", "multi-agent-trading-bot.onrender.com")
    proto = "https" if "onrender.com" in host or request.headers.get("x-forwarded-proto") == "https" else "http"
    redirect_uri = f"{proto}://{host}/api/ctrader/callback"
    auth_url = ctrader_executor.get_oauth_auth_url(redirect_uri)
    return {
        "auth_url": auth_url,
        "redirect_uri": redirect_uri,
        "client_id": ctrader_executor.CTRADER_CONFIG["client_id"]
    }

@app.get("/api/ctrader/callback")
def handle_ctrader_oauth_callback(code: str = None, error: str = None, request: Request = None):
    if error:
        return HTMLResponse(content=f"<h3>cTrader Authorization Error: {error}</h3><a href='/'>Return to Dashboard</a>")
    
    if code:
        host = request.headers.get("host", "multi-agent-trading-bot.onrender.com")
        proto = "https" if "onrender.com" in host or request.headers.get("x-forwarded-proto") == "https" else "http"
        redirect_uri = f"{proto}://{host}/api/ctrader/callback"
        
        result = ctrader_executor.exchange_oauth_code(code=code, redirect_uri=redirect_uri)
        if result.get("status") == "SUCCESS":
            return RedirectResponse(url="/?ctrader_linked=true")
        else:
            return HTMLResponse(content=f"<h3>Token Exchange Failed: {result.get('message')}</h3><a href='/'>Return to Dashboard</a>")

    return RedirectResponse(url="/")

@app.post("/api/ctrader/connect")
def connect_ctrader(req: CTraderConnectRequest):
    res = ctrader_executor.init_ctrader_connection(
        account_id=req.account_id,
        access_token=req.access_token,
        client_id=req.client_id,
        client_secret=req.client_secret,
        environment=req.environment
    )
    return res

# -------------------------------------------------------------
# cTrader cBot Webhook Bridge Endpoints (Instant Setup, No KYC)
# -------------------------------------------------------------
@app.post("/api/cbot/heartbeat")
@app.post("/api/cbot/stream")
async def cbot_heartbeat_stream(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    return cbot_bridge.update_heartbeat(data)

@app.get("/api/cbot/stream")
@app.get("/api/account/status")
@app.get("/api/cbot/status")
def get_cbot_account_status():
    return cbot_bridge.get_cbot_status()

@app.get("/api/cbot/orders")
def get_cbot_orders():
    return cbot_bridge.get_pending_orders_for_cbot()

@app.post("/api/cbot/order-filled")
def cbot_order_filled(receipt: dict):
    return cbot_bridge.record_cbot_execution(receipt)

@app.get("/api/cbot/download")
def download_cbot_file():
    path = Path(__file__).parent / "TradeTalkBridge.cs"
    if path.exists():
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=path.read_text(encoding="utf-8"), media_type="text/plain")
    return PlainTextResponse(content="// TradeTalkBridge.cs not found", status_code=404)

@app.get("/api/mt5/status")
def get_mt5_status():
    return mt5_executor.get_mt5_status()

@app.post("/api/mt5/connect")
def connect_mt5(req: MT5ConnectRequest):
    res = mt5_executor.init_mt5_connection(
        login=req.login,
        password=req.password,
        server=req.server,
        path=req.path
    )
    return res

@app.post("/api/auto-trade/toggle")
def toggle_auto_trade():
    SYSTEM_STATE["auto_trade_enabled"] = not SYSTEM_STATE["auto_trade_enabled"]
    return {
        "auto_trade_enabled": SYSTEM_STATE["auto_trade_enabled"],
        "status": "Auto-Trading ACTIVE" if SYSTEM_STATE["auto_trade_enabled"] else "Auto-Trading PAUSED"
    }

@app.post("/api/scan-now")
async def trigger_manual_scan():
    market_data = market_feed.get_live_market_data()
    results = []
    for sym in ["XAUUSD", "EURUSD"]:
        if sym in market_data:
            rec = await scan_single_market(sym, market_data[sym])
            results.append(rec)
    return {"status": "Scan Complete", "evaluated_pairs": len(results)}

@app.post("/webhook/tradingview")
async def receive_tradingview_alert(signal: TradingViewSignal):
    print(f"\n--- TradingView سگنل موصول ہوا: {signal.symbol} ({signal.action}) ---")
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    signal_id = str(uuid.uuid4())[:8]

    try:
        agent_data = await run_forex_agents(signal)
        full_analysis = agent_data["full_analysis"]
        decision_status = agent_data["decision_status"]

        summary_message = f"🚨 **نئی فاریکس ٹریڈ سمری ({signal.symbol}):**\n\n{full_analysis}"
        send_telegram_alert(summary_message)

        execution_result = None
        if decision_status == "APPROVED" and SYSTEM_STATE["auto_trade_enabled"]:
            lot_size = 0.25 if "XAU" in signal.symbol else 0.10
            execution_result = execute_order(
                symbol=signal.symbol,
                action=signal.action.upper(),
                lot_size=lot_size,
                sl=signal.stop_loss,
                tp=signal.take_profit,
                fill_price=signal.entry_price
            )

        record = {
            "id": signal_id,
            "timestamp": timestamp,
            "symbol": signal.symbol,
            "action": signal.action.upper(),
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "timeframe": signal.timeframe,
            "strategy_name": signal.strategy_name,
            "decision_status": decision_status,
            "tech_report": agent_data["tech_report"],
            "news_report": agent_data["news_report"],
            "risk_report": agent_data["risk_report"],
            "final_decision": agent_data["final_decision"],
            "analysis": full_analysis,
            "ctrader": execution_result
        }

        SIGNALS_HISTORY.insert(0, record)
        if len(SIGNALS_HISTORY) > 25:
            SIGNALS_HISTORY.pop()

        if decision_status == "APPROVED":
            return {"status": "Trade Executed", "analysis": full_analysis, "order": execution_result}
        return {"status": "Trade Rejected by Agents", "analysis": full_analysis}

    except Exception as e:
        tb = traceback.format_exc()
        print("ERROR processing alert:\n", tb)
        return {"status": "Error", "error_message": str(e), "traceback": tb}

@app.get("/api/signals")
def get_signals():
    total = len(SIGNALS_HISTORY)
    approved = sum(1 for s in SIGNALS_HISTORY if s.get("decision_status") == "APPROVED")
    rejected = sum(1 for s in SIGNALS_HISTORY if s.get("decision_status") == "REJECTED")
    rate = round((approved / total * 100), 1) if total > 0 else 0
    return {
        "signals": SIGNALS_HISTORY,
        "stats": {
            "total": total,
            "approved": approved,
            "rejected": rejected,
            "approval_rate": rate
        },
        "system_state": SYSTEM_STATE
    }

@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    template_path = Path(__file__).parent / "templates" / "dashboard.html"
    if template_path.exists():
        return HTMLResponse(content=template_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>TradeTalk AI Dashboard Loading...</h1>")

@app.get("/health")
def health_check():
    return {"status": "online", "service": "Multi-Agent Autonomous Trading System"}

# -------------------------------------------------------------
# 8. سرور اسٹارٹ کریں
# -------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    uvicorn.run(app, host="0.0.0.0", port=port)

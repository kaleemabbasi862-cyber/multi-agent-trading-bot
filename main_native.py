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

app = FastAPI(title="TradeTalk AI - Multi-Agent Forex Trading System")

# -------------------------------------------------------------
# 2. ان میموری سگنل ہسٹری (Signal History Store - Last 20)
# -------------------------------------------------------------
SIGNALS_HISTORY = [
    {
        "id": "init-01",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "symbol": "EURUSD",
        "action": "BUY",
        "entry_price": 1.0850,
        "stop_loss": 1.0820,
        "take_profit": 1.0920,
        "timeframe": "15m",
        "strategy_name": "Trend_Crossover_v1",
        "decision_status": "REJECTED",
        "tech_report": "15m ٹائم فریم پر 30 پپس کا Stop Loss اور 70 پپس کا TP (R:R = 1:2.33) تکنیکی طور پر ٹھیک ہے لیکن نزدیکی 1.0900 پر سخت مزاحمت (Resistance) موجود ہے۔ کوالٹی سکور: 65/100۔",
        "news_report": "آج کے سیشن میں US CPI ڈیٹا شیڈول ہے جس کی وجہ سے مارکیٹ میں ہائی وولٹیلیٹی کا خطرہ ہے۔ فنڈامنٹلی NO CLEARANCE برائے اسکیلپرز۔",
        "risk_report": "$10,000 اکاؤنٹ بیلنس پر 1% رسک ($100) کے تحت تجویز کردہ درست لاٹ سائز 0.33 Standard Lots ہے۔",
        "final_decision": "[DECISION: REJECTED] - فنڈامنٹل ہائی رسک نیوز اور نزدیکی ریزسٹنس کے باعث سگنل کو مسترد کیا جاتا ہے۔ تجویز کردہ لاٹ: 0.00۔",
        "analysis": "1. Technical Analysis:\n15m ٹائم فریم پر 30 پپس کا Stop Loss اور 70 پپس کا TP (R:R = 1:2.33) تکنیکی طور پر ٹھیک ہے لیکن نزدیکی 1.0900 پر سخت مزاحمت (Resistance) موجود ہے۔ کوالٹی سکور: 65/100۔\n\n2. News Analysis:\nآج کے سیشن میں US CPI ڈیٹا شیڈول ہے جس کی وجہ سے مارکیٹ میں ہائی وولٹیلیٹی کا خطرہ ہے۔ فنڈامنٹلی NO CLEARANCE برائے اسکیلپرز۔\n\n3. Risk Assessment:\n$10,000 اکاؤنٹ بیلنس پر 1% رسک ($100) کے تحت تجویز کردہ درست لاٹ سائز 0.33 Standard Lots ہے۔\n\n4. Final Desk Decision:\n[DECISION: REJECTED] - فنڈامنٹل ہائی رسک نیوز اور نزدیکی ریزسٹنس کے باعث سگنل کو مسترد کیا جاتا ہے۔ تجویز کردہ لاٹ: 0.00۔",
        "ctrader": None
    }
]

# TradingView سے آنے والے ڈیٹا کا ماڈل
class TradingViewSignal(BaseModel):
    symbol: str              # e.g., "EURUSD"
    action: str              # e.g., "BUY" or "SELL"
    entry_price: float       # e.g., 1.0850
    stop_loss: float         # e.g., 1.0820
    take_profit: float       # e.g., 1.0920
    timeframe: str           # e.g., "15m"
    strategy_name: str       # e.g., "Trend_Crossover_v1"

# -------------------------------------------------------------
# 3. cTrader اور ٹیلیگرام موک فنکشنز
# -------------------------------------------------------------
def execute_ctrader_order(symbol: str, action: str, lot_size: float, sl: float, tp: float):
    """cTrader Open API یا cBot پر آرڈر بھیجنے کا فنکشن"""
    print(f"\n[cTrader API] ٹریڈ ایگزیکیوٹ ہو گئی: {action} {lot_size} Lots of {symbol} (SL: {sl}, TP: {tp})")
    return {"status": "SUCCESS", "order_id": "CT_982341"}

def send_telegram_alert(message: str):
    """ہیومن اِن دی لوپ کے لیے الرٹ بھیجنا"""
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
# 4. ملٹی ایجنٹ متوازی پائپ لائن (Multi-Agent Consensus Pipeline)
# -------------------------------------------------------------
async def run_forex_agents(signal: TradingViewSignal) -> dict:
    llm = get_llm()

    # ایجنٹ 1: ٹیکنیکل اینالسٹ
    tech_prompt = ChatPromptTemplate.from_messages([
        ("system", "آپ 10 سال کے تجربہ کار فاریکس ٹیکنیکل اینالسٹ ہیں۔ آپ کا کام TradingView سگنل، ٹرینڈ اور پرائس ایکشن کی درستی کی توثیق کرنا اور کوالٹی سکور (1-100) دینا ہے۔"),
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

    # تینوں ایجنٹس کو ایک ساتھ متوازی ایگزیکیوٹ کریں
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
# 5. ویب ہک اینڈ پوائنٹ (Webhook Endpoint)
# -------------------------------------------------------------
@app.post("/webhook/tradingview")
async def receive_tradingview_alert(signal: TradingViewSignal):
    print(f"\n--- TradingView سے نیا سگنل موصول ہوا: {signal.symbol} ({signal.action}) ---")
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    signal_id = str(uuid.uuid4())[:8]

    try:
        agent_data = await run_forex_agents(signal)
        full_analysis = agent_data["full_analysis"]
        decision_status = agent_data["decision_status"]

        # ہیومن الرٹ
        summary_message = f"🚨 **نئی فاریکس ٹریڈ سمری ({signal.symbol}):**\n\n{full_analysis}"
        send_telegram_alert(summary_message)

        c_trade_result = None
        if decision_status == "APPROVED":
            c_trade_result = execute_ctrader_order(
                symbol=signal.symbol,
                action=signal.action,
                lot_size=0.10,
                sl=signal.stop_loss,
                tp=signal.take_profit
            )

        # ریکارڈ محفوظ کریں (Save in History)
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
            "ctrader": c_trade_result
        }

        # Keep last 20 signals at the top
        SIGNALS_HISTORY.insert(0, record)
        if len(SIGNALS_HISTORY) > 20:
            SIGNALS_HISTORY.pop()

        if decision_status == "APPROVED":
            return {"status": "Trade Executed", "analysis": full_analysis, "ctrader": c_trade_result}
        return {"status": "Trade Rejected by Agents", "analysis": full_analysis}

    except Exception as e:
        tb = traceback.format_exc()
        print("ERROR processing alert:\n", tb)
        return {
            "status": "Error",
            "error_message": str(e),
            "traceback": tb
        }

# -------------------------------------------------------------
# 6. ڈیش بورڈ API اور UI روٹس
# -------------------------------------------------------------
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
        }
    }

@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    template_path = Path(__file__).parent / "templates" / "dashboard.html"
    if template_path.exists():
        return HTMLResponse(content=template_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>TradeTalk AI Dashboard</h1><p>Template loading...</p>")

@app.get("/health")
def health_check():
    return {"status": "online", "service": "Multi-Agent AI Forex Trading System"}

# -------------------------------------------------------------
# 7. سرور اسٹارٹ کریں
# -------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    uvicorn.run(app, host="0.0.0.0", port=port)

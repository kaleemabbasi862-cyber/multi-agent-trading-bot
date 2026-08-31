import os
import sys
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
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
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
os.environ["GEMINI_API_KEY"] = GEMINI_API_KEY
os.environ["GOOGLE_API_KEY"] = GEMINI_API_KEY

llm = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
    google_api_key=GEMINI_API_KEY,
    temperature=0.2
)

app = FastAPI(title="Forex Multi-Agent Trading System (Native LangChain)")

# TradingView سے آنے والے ڈیٹا کا ماڈل
class TradingViewSignal(BaseModel):
    symbol: str              # e.g., "EURUSD"
    action: str              # e.g., "BUY" or "SELL"
    entry_price: float       # e.g., 1.0850
    stop_loss: float         # e.g., 1.0820
    take_profit: float       # e.g., 1.0920
    timeframe: str           # e.g., "15m"
    strategy_name: str       # e.g., "EMA_Crossover_RSI"

# -------------------------------------------------------------
# 2. cTrader اور ٹیلیگرام موک فنکشنز (Execution Logic)
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
# 3. ملٹی ایجنٹ پائپ لائن (Native Chain Execution)
# -------------------------------------------------------------
async def run_forex_agents(signal: TradingViewSignal) -> str:
    # ایجنٹ 1: ٹیکنیکل اینالسٹ
    tech_prompt = ChatPromptTemplate.from_messages([
        ("system", "آپ 10 سال کے تجربہ کار فاریکس ٹیکنیکل اینالسٹ ہیں۔ آپ کا کام TradingView سگنل، ٹرینڈ اور پرائس ایکشن کی درستی کی توثیق کرنا اور کوالٹی سکور (1-100) دینا ہے۔"),
        ("human", "سگنل کی جانچ کریں: Pair: {symbol}, Action: {action}, Entry: {entry}, SL: {sl}, TP: {tp}, TF: {tf}, Strategy: {strategy}")
    ])
    tech_chain = tech_prompt | llm
    tech_raw = (await tech_chain.ainvoke({
        "symbol": signal.symbol, "action": signal.action, "entry": signal.entry_price,
        "sl": signal.stop_loss, "tp": signal.take_profit, "tf": signal.timeframe,
        "strategy": signal.strategy_name
    })).content
    tech_report = extract_text(tech_raw)

    # ایجنٹ 2: فاریکس فنڈامنٹل اور نیوز اینالسٹ
    news_prompt = ChatPromptTemplate.from_messages([
        ("system", "آپ فاریکس فنڈامنٹل اینالسٹ ہیں۔ آپ مائیکرو فنڈامنٹل صورتحال اور نیوز رسک اسٹیٹس (LOW / MEDIUM / HIGH) کی جانچ کرتے ہیں۔"),
        ("human", "کرنسی پیئر {symbol} کے لیے نیوز رسک کا جائزہ لیں اور کلیئرنس رپورٹ دیں۔")
    ])
    news_chain = news_prompt | llm
    news_raw = (await news_chain.ainvoke({"symbol": signal.symbol})).content
    news_report = extract_text(news_raw)

    # ایجنٹ 3: رسک مینیجر
    risk_prompt = ChatPromptTemplate.from_messages([
        ("system", "آپ فاریکس رسک اینڈ منی مینیجر ہیں۔ اکاؤنٹ بیلنس $10,000 فرض کرتے ہوئے 1 فیصد رسک پر لاٹ سائز اور Risk-to-Reward تناسب کا تعین کریں۔"),
        ("human", "Entry: {entry}, SL: {sl}, Pair: {symbol} کے لیے لاٹ سائز اور R:R نکالیں۔")
    ])
    risk_chain = risk_prompt | llm
    risk_raw = (await risk_chain.ainvoke({
        "symbol": signal.symbol, "entry": signal.entry_price, "sl": signal.stop_loss
    })).content
    risk_report = extract_text(risk_raw)

    # ایجنٹ 4: چیف مینیجر (حتمی فیصلہ)
    manager_prompt = ChatPromptTemplate.from_messages([
        ("system", "آپ ٹریڈنگ ڈیسک کے ہیڈ ہیں۔ تمام ایجنٹس کی رپورٹس دیکھ کر حتمی فیصلہ [DECISION: APPROVED] یا [DECISION: REJECTED] دیں اور لاٹ سائز واضح کریں۔"),
        ("human", "ٹیکنیکل رپورٹ:\n{tech}\n\nنیوز رپورٹ:\n{news}\n\nرسک رپورٹ:\n{risk}\n\nحتمی فیصلہ دیں:")
    ])
    manager_chain = manager_prompt | llm
    manager_raw = (await manager_chain.ainvoke({
        "tech": tech_report, "news": news_report, "risk": risk_report
    })).content
    final_decision = extract_text(manager_raw)

    return f"**1. Technical Analysis:**\n{tech_report}\n\n**2. News Analysis:**\n{news_report}\n\n**3. Risk Assessment:**\n{risk_report}\n\n**4. Final Desk Decision:**\n{final_decision}"

# -------------------------------------------------------------
# 4. ویب ہک اینڈ پوائنٹ
# -------------------------------------------------------------
@app.post("/webhook/tradingview")
async def receive_tradingview_alert(signal: TradingViewSignal):
    print(f"\n--- TradingView سے نیا سگنل موصول ہوا: {signal.symbol} ({signal.action}) ---")
    
    result = await run_forex_agents(signal)
    
    # ہیومن الرٹ
    summary_message = f"🚨 **نئی فاریکس ٹریڈ سمری:**\n\n{result}"
    send_telegram_alert(summary_message)

    # اگر مینیجر نے منظوری دی ہو تو cTrader پر ٹریڈ بھیجیں
    if "APPROVED" in str(result):
        c_trade_result = execute_ctrader_order(
            symbol=signal.symbol,
            action=signal.action,
            lot_size=0.10,
            sl=signal.stop_loss,
            tp=signal.take_profit
        )
        return {"status": "Trade Executed", "analysis": result, "ctrader": c_trade_result}
    
    return {"status": "Trade Rejected by Agents", "analysis": result}

# -------------------------------------------------------------
# 5. سرور اسٹارٹ کریں
# -------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

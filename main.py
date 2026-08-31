import os
import sys
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from crewai import Agent, Crew, Process, Task
from langchain_google_genai import ChatGoogleGenerativeAI
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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
os.environ["GEMINI_API_KEY"] = GEMINI_API_KEY or ""

# LLM ماڈل کنفیگریشن
llm = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
    google_api_key=GEMINI_API_KEY,
    temperature=0.2
)

app = FastAPI(title="Forex Multi-Agent Trading System")

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

# -------------------------------------------------------------
# 3. ملٹی ایجنٹس کی تیاری (CrewAI Agents)
# -------------------------------------------------------------

# ایجنٹ 1: مارکیٹ اور ٹیکنیکل سگنل اینالسٹ
technical_agent = Agent(
    role="Forex Technical Analyst",
    goal="TradingView سگنل، ٹرینڈ اور پرائس ایکشن کی درستی کی توثیق کرنا۔",
    backstory="آپ 10 سال کے تجربہ کار فاریکس ٹیکنیکل اینالسٹ ہیں۔ آپ فیک بریک آؤٹس اور غلط سگنلز کو فوری پکڑ لیتے ہیں۔",
    llm=llm,
    verbose=True
)

# ایجنٹ 2: فاریکس نیوز اور سینٹیمنٹ اینالسٹ
news_agent = Agent(
    role="Forex Fundamental & News Analyst",
    goal="اکنامک ڈیٹا (NFP, CPI, Interest Rates) اور مارکیٹ سینٹیمنٹ کی جانچ کرنا۔",
    backstory="آپ فنانشل مارکیٹ کی تمام ہائی امپیکٹ نیوز اور کرنسی سینٹیمنٹ پر کڑی نظر رکھتے ہیں تاکہ نیوز کے وقت ٹریڈ بلاک کی جا سکے۔",
    llm=llm,
    verbose=True
)

# ایجنٹ 3: رسک مینیجر اور پوزیشن سائزر
risk_agent = Agent(
    role="Forex Risk & Money Manager",
    goal="اکاؤنٹ بیلنس کے مطابق لاٹ سائز اور رسک ٹو ریوارڈ ریشو (R:R) کا درست تعین کرنا۔",
    backstory="آپ کے نزدیک کیپٹل کا تحفظ سب سے اہم ہے۔ آپ 1 فیصد سے زیادہ رسک اور 1:2 سے کم R:R والی ٹریڈ کبھی منظور نہیں کرتے۔",
    llm=llm,
    verbose=True
)

# ایجنٹ 4: چیف ٹریڈنگ ڈیسک مینیجر
manager_agent = Agent(
    role="Head of Trading Desk",
    goal="تمام ایجنٹس کے ڈیٹا کو دیکھ کر حتمی فیصلہ (APPROVE یا REJECT) دینا۔",
    backstory="آپ ٹریڈنگ ڈیسک کے ہیڈ ہیں۔ تمام ایجنٹس آپ کو رپورٹ کرتے ہیں اور ٹریڈ لینے یا چھوڑنے کا حتمی فیصلہ آپ کا ہوتا ہے۔",
    llm=llm,
    verbose=True
)

# -------------------------------------------------------------
# 4. ویب ہک اینڈ پوائنٹ اور آرکیسٹریشن
# -------------------------------------------------------------
@app.post("/webhook/tradingview")
async def receive_tradingview_alert(signal: TradingViewSignal):
    print(f"\n--- TradingView سے نیا سگنل موصول ہوا: {signal.symbol} ({signal.action}) ---")
    
    # ٹاسک 1: ٹیکنیکل ویلیڈیشن
    task_tech = Task(
        description=f"سگنل کی جانچ کریں: Pair: {signal.symbol}, Action: {signal.action}, Entry: {signal.entry_price}, SL: {signal.stop_loss}, TP: {signal.take_profit}, TF: {signal.timeframe}۔ بتائیں کہ کیا یہ سیٹ اپ منطقی ہے؟",
        expected_output="ٹیکنیکل ویلیڈیشن رپورٹ اور سیٹ اپ کی کوالٹی سکور (1-100)۔",
        agent=technical_agent
    )

    # ٹاسک 2: نیوز چیک
    task_news = Task(
        description=f"کرنسی پیئر {signal.symbol} کے لیے مائیکرو فنڈامنٹل صورتحال کا جائزہ لیں۔ کیا اگلے کچھ گھنٹوں میں کوئی بڑا فنانشل ایونٹ خطرہ پیدا کر سکتا ہے؟",
        expected_output="نیوز رسک اسٹیٹس (LOW / MEDIUM / HIGH) اور کلیئرنس۔",
        agent=news_agent
    )

    # ٹاسک 3: رسک مینجمنٹ
    task_risk = Task(
        description=f"اکاؤنٹ بیلنس $10,000 فرض کرتے ہوئے، 1% رسک پر {signal.symbol} کے لیے لاٹ سائز کیلکولیٹ کریں (Entry: {signal.entry_price}, SL: {signal.stop_loss})۔",
        expected_output="تجویز کردہ درست لاٹ سائز (Lot Size) اور Risk-to-Reward تناسب۔",
        agent=risk_agent
    )

    # ٹاسک 4: حتمی ایگزیکیوشن فیصلہ
    task_execution = Task(
        description="پچھلے تمام ٹاسکس کی بنیاد پر حتمی رپورٹ بنائیں اور فیصلہ دیں: [DECISION: APPROVED] یا [DECISION: REJECTED]۔ اگر منظور ہو تو لاٹ سائز بھی واضح کریں۔",
        expected_output="حتمی ٹریڈ سمری اور منظوری کا فیصلہ۔",
        agent=manager_agent
    )

    # ملٹی ایجنٹ ٹیم ورک فلو
    forex_crew = Crew(
        agents=[technical_agent, news_agent, risk_agent, manager_agent],
        tasks=[task_tech, task_news, task_risk, task_execution],
        process=Process.sequential,
        verbose=True
    )

    # ایجنٹس کا متفقہ تجزیہ حاصل کریں
    result = forex_crew.kickoff()
    
    # ہیومن الرٹ
    summary_message = f"🚨 **نئی فاریکس ٹریڈ سمری:**\n\n{result}"
    send_telegram_alert(summary_message)

    # اگر مینیجر نے منظوری دی ہو تو cTrader پر ٹریڈ بھیجیں
    if "APPROVED" in str(result):
        # عام طور پر رسک ایجنٹ سے لاٹ سائز نکالا جاتا ہے (مثال: 0.10)
        c_trade_result = execute_ctrader_order(
            symbol=signal.symbol,
            action=signal.action,
            lot_size=0.10,
            sl=signal.stop_loss,
            tp=signal.take_profit
        )
        return {"status": "Trade Executed", "analysis": str(result), "ctrader": c_trade_result}
    
    return {"status": "Trade Rejected by Agents", "analysis": str(result)}

# -------------------------------------------------------------
# 5. سرور اسٹارٹ کریں
# -------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

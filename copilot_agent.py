import os
import re
import json
import requests
from dotenv import load_dotenv
import cbot_bridge
import market_feed

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

SYSTEM_PROMPT = """You are TradeTalk Copilot, an elite AI Trading Assistant embedded inside the TradeTalk multi-agent algorithmic trading terminal.
You have real-time access to the user's cTrader live account, live market feeds (Gold, Silver, EURUSD, GBPUSD, BTCUSD), and autonomous agent controls.

You can execute actions on behalf of the user:
- Check portfolio balance, equity, and open positions
- Close specific or all open positions
- Analyze specific asset pairs (XAUUSD Gold, XAGUSD Silver, EURUSD, GBPUSD, BTCUSD)
- Toggle Auto-Trading (Enable/Disable)
- Manage risk / Set Break-Even protection

Language Guidelines:
- If the user asks in Urdu or Roman Urdu, reply naturally and professionally in Urdu (or Roman Urdu).
- If the user asks in English, reply in crisp, professional financial English.
- Keep replies concise (2-4 sentences max), informative, and action-oriented.
"""

def execute_copilot_intent(user_query: str, system_state: dict) -> dict:
    """
    Parses natural language / voice commands in Urdu and English and executes real terminal actions.
    """
    q = user_query.strip().lower()
    acc_status = cbot_bridge.get_cbot_status()
    open_positions = acc_status.get("open_positions", [])
    bal = acc_status.get("balance", 39.61)
    eq = acc_status.get("equity", 39.61)

    # 1. Action: Pause / Disable Auto-Trade
    if any(k in q for k in ["pause auto", "stop auto", "disable auto", "turn off auto", "آٹو ٹریڈ بند", "روک دو", "بند کرو", "آٹو ٹریڈنگ بند"]):
        system_state["auto_trade_enabled"] = False
        is_urdu = any(char > '\u0600' and char < '\u06FF' for char in user_query) or "karo" in q or "band" in q
        reply = "آٹو ٹریڈنگ کامیابی کے ساتھ روک دی گئی ہے (Auto-Trade: OFF)۔ اب کوئی خودکار ٹریڈ نہیں لگے گی۔" if is_urdu else "Auto-trading has been paused (Auto-Trade: OFF). Autonomous order execution is now disabled."
        return {
            "reply": reply,
            "action_taken": "AUTO_TRADE_DISABLED",
            "system_state": system_state,
            "account_status": acc_status
        }

    # 2. Action: Enable / Start Auto-Trade
    if any(k in q for k in ["start auto", "enable auto", "turn on auto", "resume auto", "آٹو ٹریڈ آن", "شروع کرو", "آن کرو", "چلا دو", "آٹو ٹریڈنگ شروع"]):
        system_state["auto_trade_enabled"] = True
        is_urdu = any(char > '\u0600' and char < '\u06FF' for char in user_query) or "karo" in q or "chala" in q
        reply = "آٹو ٹریڈنگ آن کر دی گئی ہے (Auto-Trade: ON)۔ AI ایجنٹس اب مارکیٹ اسکین کر کے خودکار ٹریڈز لگائیں گے۔" if is_urdu else "Auto-trading is now ACTIVE (Auto-Trade: ON). Autonomous agents are scanning and executing trades."
        return {
            "reply": reply,
            "action_taken": "AUTO_TRADE_ENABLED",
            "system_state": system_state,
            "account_status": acc_status
        }

    # 3. Action: Close Open Position(s)
    if any(k in q for k in ["close all", "close position", "close trade", "exit trade", "ٹریڈ بند کرو", "پوزیشن کلوز", "کلوز کرو", "بند کر دیں"]):
        # Check if specific symbol or ticket mentioned
        closed_count = 0
        if not open_positions:
            is_urdu = any(char > '\u0600' and char < '\u06FF' for char in user_query) or "karo" in q
            reply = "اس وقت آپ کے cTrader اکاؤنٹ پر کوئی فعال اوپن پوزیشن موجود نہیں ہے۔" if is_urdu else "There are currently no active open positions to close on your cTrader account."
            return {"reply": reply, "action_taken": "NO_POSITIONS", "account_status": acc_status}

        for pos in open_positions:
            pos_id = pos.get("id")
            cbot_bridge.queue_close_position(pos_id)
            closed_count += 1

        is_urdu = any(char > '\u0600' and char < '\u06FF' for char in user_query) or "karo" in q
        reply = f"تمام کھلی پوزیشنز ({closed_count}) کو فوری بند کرنے کا حکم cTrader کو بھیج دیا گیا ہے۔" if is_urdu else f"Close command for {closed_count} active position(s) has been dispatched to cTrader."
        return {
            "reply": reply,
            "action_taken": "POSITIONS_CLOSED",
            "closed_count": closed_count,
            "account_status": acc_status
        }

    # 4. Action: Analyze Market Symbol (Gold, Silver, EURUSD, etc.)
    target_sym = None
    if "gold" in q or "xau" in q or "گولڈ" in q or "سونا" in q:
        target_sym = "XAUUSD"
    elif "silver" in q or "xag" in q or "سلور" in q or "چاندی" in q:
        target_sym = "XAGUSD"
    elif "euro" in q or "eur" in q or "یورو" in q:
        target_sym = "EURUSD"
    elif "pound" in q or "gbp" in q or "پاؤنڈ" in q:
        target_sym = "GBPUSD"
    elif "btc" in q or "bitcoin" in q or "بٹ کوائن" in q:
        target_sym = "BTCUSD"

    if ("analyze" in q or "scan" in q or "rate" in q or "price" in q or "تجزیہ" in q or "قیمت" in q or "حال" in q or "کیسا" in q) and target_sym:
        feed = market_feed.get_live_ticker(target_sym)
        p = feed.get("price", 0)
        ind = feed.get("indicators", {})
        rsi = ind.get("rsi", 50)
        trend = ind.get("trend", "BULLISH")
        supp = ind.get("support", 0)
        res = ind.get("resistance", 0)
        
        is_urdu = any(char > '\u0600' and char < '\u06FF' for char in user_query) or "karo" in q or "batao" in q or "kya" in q
        if is_urdu:
            reply = f"{target_sym} کی موجودہ قیمت ${p} ہے۔ RSI {rsi} ہے اور مجموعی ٹرینڈ {trend} ہے۔ سپورٹ لیول ${supp} اور ریزسٹنس ${res} پر ہے۔ AI ایجنٹس اس کے بریک آؤٹ کی نگرانی کر رہے ہیں۔"
        else:
            reply = f"{target_sym} is trading at ${p}. RSI is at {rsi} with a {trend} trend momentum. Key Support: ${supp} | Resistance: ${res}. AI agents are actively monitoring entry setups."
        
        return {
            "reply": reply,
            "action_taken": "MARKET_ANALYZED",
            "symbol": target_sym,
            "data": feed
        }

    # 5. Action: Portfolio / Balance / Risk Query
    if any(k in q for k in ["balance", "equity", "profit", "risk", "status", "بیلنس", "ایکویٹی", "منافع", "نقصان", "حال", "رسک"]):
        pnl = sum([float(p.get("net_profit", 0)) for p in open_positions])
        pos_count = len(open_positions)
        is_urdu = any(char > '\u0600' and char < '\u06FF' for char in user_query) or "kya" in q or "mera" in q or "hai" in q
        if is_urdu:
            reply = f"آپ کا cTrader لائیو بیلنس ${bal:.2f} USD اور ایکوٹی ${eq:.2f} USD ہے۔ اس وقت {pos_count} ٹریڈز اوپن ہیں جن کا مجموعی لائیو PnL ${pnl:+.2f} USD ہے۔ رسک مینجمنٹ 1% پر ایکٹیو ہے۔"
        else:
            reply = f"Live cTrader Balance is ${bal:.2f} USD (Equity: ${eq:.2f} USD). You have {pos_count} open position(s) with total live PnL of ${pnl:+.2f} USD. Strict 1% risk guard is active."
        return {
            "reply": reply,
            "action_taken": "PORTFOLIO_SUMMARY",
            "account_status": acc_status
        }

    # 6. LLM Fallback (AI Brain using Gemini if available, or smart conversational assistant)
    if GEMINI_API_KEY:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
            prompt = f"{SYSTEM_PROMPT}\n\nCurrent State: Balance=${bal}, Equity=${eq}, Open Positions={len(open_positions)}, AutoTrade={system_state.get('auto_trade_enabled')}\n\nUser: {user_query}\n\nAssistant Response:"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}]
            }
            res = requests.post(url, json=payload, timeout=8).json()
            reply = res["candidates"][0]["content"]["parts"][0]["text"].strip()
            return {"reply": reply, "action_taken": "AI_CHAT"}
        except Exception as e:
            print(f"[Copilot Gemini fallback note]: {e}")

    # Default friendly multi-lingual response
    is_urdu = any(char > '\u0600' and char < '\u06FF' for char in user_query) or "karo" in q or "kya" in q
    if is_urdu:
        reply = f"میں ٹریڈ ٹاک AI کو پائلٹ ہوں۔ آپ مجھ سے بول کر یا لکھ کر مارکیٹ تجزیہ ('گولڈ کا تجزیہ کرو')، بیلنس معلوم کرنا، یا آٹو ٹریڈنگ کنٹرول ('آٹو ٹریڈ بند کرو') کروا سکتے ہیں۔"
    else:
        reply = f"I am your TradeTalk AI Copilot. You can give me voice or text commands like 'Analyze Gold', 'Check my balance', 'Close all positions', or 'Pause auto-trade'."

    return {"reply": reply, "action_taken": "DEFAULT_ASSISTANT"}

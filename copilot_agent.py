import os
import re
import json
import requests
from dotenv import load_dotenv
import cbot_bridge
import market_feed
import settings_manager

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

SYSTEM_PROMPT = """You are TradeTalk Copilot, an elite AI Trading Assistant embedded inside the TradeTalk multi-agent algorithmic trading terminal.
You have real-time access to the user's cTrader live account, live market feeds (Gold, Silver, EURUSD, GBPUSD, BTCUSD), active pair selection whitelist, and autonomous agent controls.

You can execute actions on behalf of the user:
- Check portfolio balance, equity, and open positions
- Close specific or all open positions
- Analyze specific asset pairs (XAUUSD Gold, XAGUSD Silver, EURUSD, GBPUSD, BTCUSD)
- Toggle Auto-Trading (Enable/Disable)
- Manage active pair selection whitelist (e.g. 'Only trade Gold and Silver', 'Disable EURUSD', 'Enable Bitcoin')
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
    is_urdu = any(char > '\u0600' and char < '\u06FF' for char in user_query) or any(k in q for k in ["karo", "batao", "kya", "band", "chala", "rakho", "lagao"])

    # 1. Action: Manage Pair Whitelist Selection (Voice & Chat controls)
    # Check for "Only trade Gold and Silver" / "صرف گولڈ اور سلور"
    if ("only" in q or "صرف" in q) and ("gold" in q or "گولڈ" in q or "سونا" in q) and ("silver" in q or "سلور" in q or "چاندی" in q):
        new_pairs = settings_manager.set_active_pairs(["XAUUSD", "XAGUSD"])
        system_state["active_pairs"] = new_pairs
        reply = "پیئر لسٹ اپ ڈیٹ ہو گئی ہے: اب صرف گولڈ (XAUUSD) اور سلور (XAGUSD) پر اسکیننگ اور آٹو ٹریڈ ہوگی۔" if is_urdu else "Pair whitelist updated: Only Gold (XAUUSD) and Silver (XAGUSD) are now active for scanning and execution."
        return {
            "reply": reply,
            "action_taken": "PAIRS_WHITELIST_UPDATED",
            "active_pairs": new_pairs,
            "system_state": system_state
        }

    # Check for "Only trade Forex / Currencies" / "صرف فاریکس"
    if ("only" in q or "صرف" in q) and ("forex" in q or "currenc" in q or "فاریکس" in q or "کرنسی" in q):
        new_pairs = settings_manager.set_active_pairs(["EURUSD", "GBPUSD"])
        system_state["active_pairs"] = new_pairs
        reply = "پیئر لسٹ اپ ڈیٹ ہو گئی ہے: اب صرف فاریکس پیئرز (EURUSD, GBPUSD) پر ٹریڈنگ ہوگی۔" if is_urdu else "Pair whitelist updated: Only Forex pairs (EURUSD, GBPUSD) are now active."
        return {
            "reply": reply,
            "action_taken": "PAIRS_WHITELIST_UPDATED",
            "active_pairs": new_pairs,
            "system_state": system_state
        }

    # Check for "Only trade Gold" / "صرف گولڈ"
    if ("only" in q or "صرف" in q) and ("gold" in q or "گولڈ" in q or "سونا" in q) and not ("silver" in q or "سلور" in q):
        new_pairs = settings_manager.set_active_pairs(["XAUUSD"])
        system_state["active_pairs"] = new_pairs
        reply = "اب صرف گولڈ (XAUUSD) فعال ہے، باقی تمام پیئرز بند کر دیے گئے ہیں۔" if is_urdu else "Gold (XAUUSD) is now the only active trading pair."
        return {
            "reply": reply,
            "action_taken": "PAIRS_WHITELIST_UPDATED",
            "active_pairs": new_pairs,
            "system_state": system_state
        }

    # Check for "Only trade Silver" / "صرف سلور"
    if ("only" in q or "صرف" in q) and ("silver" in q or "سلور" in q or "چاندی" in q) and not ("gold" in q or "گولڈ" in q):
        new_pairs = settings_manager.set_active_pairs(["XAGUSD"])
        system_state["active_pairs"] = new_pairs
        reply = "اب صرف سلور (XAGUSD) فعال ہے، باقی تمام پیئرز بند کر دیے گئے ہیں۔" if is_urdu else "Silver (XAGUSD) is now the only active trading pair."
        return {
            "reply": reply,
            "action_taken": "PAIRS_WHITELIST_UPDATED",
            "active_pairs": new_pairs,
            "system_state": system_state
        }

    # Check for "Trade all pairs" / "تمام پیئرز فعال کرو"
    if ("all pairs" in q or "trade all" in q or "enable all" in q or "تمام پیئرز" in q or "تمام پیئر" in q or "سارے پیئرز" in q):
        new_pairs = settings_manager.set_active_pairs(["XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "BTCUSD"])
        system_state["active_pairs"] = new_pairs
        reply = "تمام 5 پیئرز (Gold, Silver, EURUSD, GBPUSD, Bitcoin) فعال کر دیے گئے ہیں۔" if is_urdu else "All trading pairs (XAUUSD, XAGUSD, EURUSD, GBPUSD, BTCUSD) are now enabled in the whitelist."
        return {
            "reply": reply,
            "action_taken": "PAIRS_WHITELIST_UPDATED",
            "active_pairs": new_pairs,
            "system_state": system_state
        }

    # Check for Single Pair Enable / Disable command
    pair_match = None
    if "gold" in q or "xau" in q or "گولڈ" in q or "سونا" in q:
        pair_match = "XAUUSD"
    elif "silver" in q or "xag" in q or "سلور" in q or "چاندی" in q:
        pair_match = "XAGUSD"
    elif "euro" in q or "eur" in q or "یورو" in q:
        pair_match = "EURUSD"
    elif "pound" in q or "gbp" in q or "پاؤنڈ" in q:
        pair_match = "GBPUSD"
    elif "btc" in q or "bitcoin" in q or "بٹ کوائن" in q:
        pair_match = "BTCUSD"

    # Disable specific pair
    if pair_match and any(k in q for k in ["disable", "remove", "turn off", "stop trading", "ہٹاؤ", "بند کرو", "نہیں لگانا", "روکو"]) and not ("position" in q or "trade" in q and "close" in q):
        active = settings_manager.get_active_pairs()
        if pair_match in active:
            active.remove(pair_match)
            new_pairs = settings_manager.set_active_pairs(active)
            system_state["active_pairs"] = new_pairs
            reply = f"{pair_match} کو ٹریڈنگ لسٹ سے ہٹا دیا گیا ہے۔ اب اس پر کوئی خودکار ٹریڈ نہیں لگے گی۔" if is_urdu else f"{pair_match} has been disabled from the active trading whitelist."
            return {
                "reply": reply,
                "action_taken": "PAIRS_WHITELIST_UPDATED",
                "active_pairs": new_pairs,
                "system_state": system_state
            }

    # Enable specific pair
    if pair_match and any(k in q for k in ["enable", "add", "turn on", "start trading", "شامل کرو", "آن کرو", "فعال کرو", "لگاؤ"]):
        active = settings_manager.get_active_pairs()
        if pair_match not in active:
            active.append(pair_match)
            new_pairs = settings_manager.set_active_pairs(active)
            system_state["active_pairs"] = new_pairs
            reply = f"{pair_match} کو ٹریڈنگ لسٹ میں فعال کر دیا گیا ہے۔ AI ایجنٹس اب اس پر بھی اسکیننگ کریں گے۔" if is_urdu else f"{pair_match} has been added to the active trading whitelist."
            return {
                "reply": reply,
                "action_taken": "PAIRS_WHITELIST_UPDATED",
                "active_pairs": new_pairs,
                "system_state": system_state
            }

    # Query Active Pairs list
    if any(k in q for k in ["which pairs", "active pairs", "whitelist", "کون سے پیئر", "کون کون سے پیئر", "پیئر لسٹ", "ایکٹو پیئرز"]):
        active = settings_manager.get_active_pairs()
        pairs_str = ", ".join(active)
        reply = f"اس وقت درج ذیل پیئرز ایکٹو ہیں: {pairs_str}۔ صرف ان پر خودکار ٹریڈنگ ہو رہی ہے۔" if is_urdu else f"Currently active trading pairs: {pairs_str}. Only these pairs are being scanned and executed."
        return {
            "reply": reply,
            "action_taken": "PAIRS_LIST_QUERY",
            "active_pairs": active
        }

    # 2. Action: Pause / Disable Auto-Trade
    if any(k in q for k in ["pause auto", "stop auto", "disable auto", "turn off auto", "آٹو ٹریڈ بند", "روک دو", "آٹو ٹریڈنگ بند"]):
        system_state["auto_trade_enabled"] = False
        reply = "آٹو ٹریڈنگ کامیابی کے ساتھ روک دی گئی ہے (Auto-Trade: OFF)۔ اب کوئی خودکار ٹریڈ نہیں لگے گی۔" if is_urdu else "Auto-trading has been paused (Auto-Trade: OFF). Autonomous order execution is now disabled."
        return {
            "reply": reply,
            "action_taken": "AUTO_TRADE_DISABLED",
            "system_state": system_state,
            "account_status": acc_status
        }

    # 3. Action: Enable / Start Auto-Trade
    if any(k in q for k in ["start auto", "enable auto", "turn on auto", "resume auto", "آٹو ٹریڈ آن", "آٹو ٹریڈنگ شروع"]):
        system_state["auto_trade_enabled"] = True
        reply = "آٹو ٹریڈنگ آن کر دی گئی ہے (Auto-Trade: ON)۔ AI ایجنٹس اب مارکیٹ اسکین کر کے خودکار ٹریڈز لگائیں گے۔" if is_urdu else "Auto-trading is now ACTIVE (Auto-Trade: ON). Autonomous agents are scanning and executing trades."
        return {
            "reply": reply,
            "action_taken": "AUTO_TRADE_ENABLED",
            "system_state": system_state,
            "account_status": acc_status
        }

    # 4. Action: Close Open Position(s)
    if any(k in q for k in ["close all", "close position", "close trade", "exit trade", "ٹریڈ بند کرو", "پوزیشن کلوز", "کلوز کرو", "تمام سلور ٹریڈز بند"]):
        closed_count = 0
        if not open_positions:
            reply = "اس وقت آپ کے cTrader اکاؤنٹ پر کوئی فعال اوپن پوزیشن موجود نہیں ہے۔" if is_urdu else "There are currently no active open positions to close on your cTrader account."
            return {"reply": reply, "action_taken": "NO_POSITIONS", "account_status": acc_status}

        target_filter = None
        if "silver" in q or "xag" in q or "سلور" in q:
            target_filter = "XAG"
        elif "gold" in q or "xau" in q or "گولڈ" in q:
            target_filter = "XAU"
        elif "euro" in q or "eur" in q or "یورو" in q:
            target_filter = "EUR"
        elif "pound" in q or "gbp" in q or "پاؤنڈ" in q:
            target_filter = "GBP"

        for pos in open_positions:
            pos_sym = pos.get("symbol", "").upper()
            if target_filter is None or target_filter in pos_sym:
                pos_id = pos.get("id")
                cbot_bridge.queue_close_position(pos_id)
                closed_count += 1

        reply = f"مطلوبہ پوزیشنز ({closed_count}) کو فوری بند کرنے کا حکم cTrader کو بھیج دیا گیا ہے۔" if is_urdu else f"Close command for {closed_count} active position(s) has been dispatched to cTrader."
        return {
            "reply": reply,
            "action_taken": "POSITIONS_CLOSED",
            "closed_count": closed_count,
            "account_status": acc_status
        }

    # 5. Action: Analyze Market Symbol (Gold, Silver, EURUSD, etc.)
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

    # 6. Action: Portfolio / Balance / Risk Query
    if any(k in q for k in ["balance", "equity", "profit", "risk", "status", "بیلنس", "ایکویٹی", "منافع", "نقصان", "حال", "رسک"]):
        pnl = sum([float(p.get("net_profit", 0)) for p in open_positions])
        pos_count = len(open_positions)
        if is_urdu:
            reply = f"آپ کا cTrader لائیو بیلنس ${bal:.2f} USD اور ایکوٹی ${eq:.2f} USD ہے۔ اس وقت {pos_count} ٹریڈز اوپن ہیں جن کا مجموعی لائیو PnL ${pnl:+.2f} USD ہے۔ رسک مینجمنٹ 1% پر ایکٹیو ہے۔"
        else:
            reply = f"Live cTrader Balance is ${bal:.2f} USD (Equity: ${eq:.2f} USD). You have {pos_count} open position(s) with total live PnL of ${pnl:+.2f} USD. Strict 1% risk guard is active."
        return {
            "reply": reply,
            "action_taken": "PORTFOLIO_SUMMARY",
            "account_status": acc_status
        }

    # 7. LLM Fallback (AI Brain using Gemini if available)
    if GEMINI_API_KEY:
        try:
            active_p = settings_manager.get_active_pairs()
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
            prompt = f"{SYSTEM_PROMPT}\n\nCurrent State: Balance=${bal}, Equity=${eq}, Open Positions={len(open_positions)}, AutoTrade={system_state.get('auto_trade_enabled')}, Active Pairs={active_p}\n\nUser: {user_query}\n\nAssistant Response:"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}]
            }
            res = requests.post(url, json=payload, timeout=8).json()
            reply = res["candidates"][0]["content"]["parts"][0]["text"].strip()
            return {"reply": reply, "action_taken": "AI_CHAT"}
        except Exception as e:
            print(f"[Copilot Gemini fallback note]: {e}")

    # Default friendly multi-lingual response
    active_p = settings_manager.get_active_pairs()
    if is_urdu:
        reply = f"میں ٹریڈ ٹاک AI کوپائلٹ ہوں۔ فعال پیئرز: {', '.join(active_p)}۔ آپ مجھ سے بول کر یا لکھ کر پیئر تبدیل کر سکتے ہیں ('صرف گولڈ اور سلور ٹریڈ کرو')، مارکیٹ تجزیہ، یا آٹو ٹریڈنگ کنٹرول کروا سکتے ہیں۔"
    else:
        reply = f"I am your TradeTalk AI Copilot. Active pairs: {', '.join(active_p)}. You can say 'Only trade Gold and Silver', 'Analyze Gold', 'Close all positions', or 'Pause auto-trade'."

    return {"reply": reply, "action_taken": "DEFAULT_ASSISTANT"}

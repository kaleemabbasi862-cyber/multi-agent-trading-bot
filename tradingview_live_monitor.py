import os
import sys
import time
import asyncio
import argparse
import re
from datetime import datetime
import requests
from playwright.async_api import async_playwright

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Webhook Endpoints
LOCAL_WEBHOOK_URL = "http://localhost:8000/webhook/tradingview"
CLOUD_WEBHOOK_URL = "https://multi-agent-trading-bot.onrender.com/webhook/tradingview"

def send_signal_to_webhook(payload: dict):
    """Send detected signal to both local server (if active) and cloud webhook."""
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🚀 Dispatched Signal: {payload['symbol']} ({payload['action']}) @ {payload['entry_price']}")
    
    # Try local webhook first
    try:
        res = requests.post(LOCAL_WEBHOOK_URL, json=payload, timeout=5)
        if res.status_code == 200:
            print(f"  [+] Local Webhook Status: 200 OK -> {res.json().get('status')}")
    except Exception:
        pass  # Local server might not be running, that's fine

    # Dispatch to live Render cloud
    try:
        print(f"  [*] Forwarding to Live Cloud: {CLOUD_WEBHOOK_URL}...")
        res = requests.post(CLOUD_WEBHOOK_URL, json=payload, timeout=45)
        if res.status_code == 200:
            data = res.json()
            status = data.get("status", "Analyzed")
            print(f"  [+] Cloud Consensus Result: {status}")
            print(f"  [+] Dashboard Updated: https://multi-agent-trading-bot.onrender.com")
        else:
            print(f"  [!] Cloud returned HTTP {res.status_code}")
    except Exception as e:
        print(f"  [!] Cloud webhook delivery error: {e}")

async def extract_tradingview_price(page) -> float:
    """Extract current live price from TradingView chart via multiple DOM strategies."""
    try:
        # Strategy 1: Read from document.title (e.g. '2,745.50 Gold / U.S. Dollar ...')
        title = await page.title()
        title_matches = re.findall(r"[\d,]+\.\d+", title)
        if title_matches:
            clean_val = title_matches[0].replace(",", "")
            val = float(clean_val)
            if val > 0:
                return val

        # Strategy 2: Look for legend price or last-price DOM elements
        selectors = [
            "[data-name='legend-last-value']",
            ".pane-legend-item-value",
            "[class*='last-']",
            "[class*='priceValue']",
            ".js-symbol-last"
        ]
        for sel in selectors:
            elems = await page.query_selector_all(sel)
            for el in elems:
                txt = await el.inner_text()
                nums = re.findall(r"[\d,]+\.\d+", txt)
                if nums:
                    val = float(nums[0].replace(",", ""))
                    if val > 0:
                        return val
    except Exception:
        pass
    return None

async def monitor_tradingview(symbol: str = "OANDA:XAUUSD", headless: bool = False, poll_interval: int = 3):
    session_dir = os.path.abspath("./tv_session")
    os.makedirs(session_dir, exist_ok=True)
    
    clean_symbol = symbol.split(":")[-1] if ":" in symbol else symbol
    chart_url = f"https://www.tradingview.com/chart/?symbol={symbol}"

    print("================================================================")
    print("      TradeTalk AI - Autonomous TradingView Monitor Agent       ")
    print("================================================================")
    print(f"[*] Target Symbol   : {symbol} ({clean_symbol})")
    print(f"[*] Session Storage : {session_dir}")
    print(f"[*] Chart URL       : {chart_url}")
    print(f"[*] Polling Loop    : Every {poll_interval} seconds")
    print(f"[*] Live Dashboard  : https://multi-agent-trading-bot.onrender.com")
    print("================================================================\n")

    async with async_playwright() as p:
        # Launch Chromium persistent browser session
        print("[*] Launching Chromium persistent browser session...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=session_dir,
            headless=headless,
            viewport={"width": 1366, "height": 768},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized"
            ]
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        print(f"[*] Navigating to TradingView chart: {chart_url}...")
        try:
            await page.goto(chart_url, wait_until="domcontentloaded", timeout=45000)
            print("[+] Chart loaded successfully.")
        except Exception as e:
            print(f"[!] Page load note: {e}. Continuing monitoring...")

        last_price = None
        price_history = []
        iteration = 0

        print("\n[*] Autonomous Real-Time Monitoring Loop Started...")
        print("[*] (Press Ctrl+C to stop monitoring at any time)\n")

        try:
            while True:
                iteration += 1
                current_price = await extract_tradingview_price(page)

                if current_price:
                    price_history.append(current_price)
                    if len(price_history) > 30:
                        price_history.pop(0)

                    # Calculate momentum / direction
                    diff = 0.0
                    if last_price:
                        diff = current_price - last_price

                    diff_str = f"+{diff:.2f}" if diff >= 0 else f"{diff:.2f}"
                    timestamp_str = datetime.now().strftime("%H:%M:%S")

                    print(f"[{timestamp_str}] [Live Feed] {clean_symbol} Price: ${current_price:,.2f} ({diff_str}) | Iteration #{iteration}", end="\r")

                    # Scan for alert popups or visual indicator markers in chart DOM
                    chart_text = ""
                    try:
                        chart_text = await page.inner_text("body")
                    except Exception:
                        pass

                    # Detect signal keywords
                    detected_action = None
                    strategy_name = "Live_DOM_Tracker"

                    if "BUY SIGNAL" in chart_text.upper() or "BUYING WHALE" in chart_text.upper():
                        detected_action = "BUY"
                        strategy_name = "Whale_Orderflow_Tracker"
                    elif "SELL SIGNAL" in chart_text.upper() or "SELLING WHALE" in chart_text.upper():
                        detected_action = "SELL"
                        strategy_name = "Whale_Orderflow_Tracker"

                    # Calculate SL and TP based on typical Gold / Forex distance
                    if detected_action:
                        sl_offset = 12.0 if "XAU" in clean_symbol else (current_price * 0.003)
                        tp_offset = 25.0 if "XAU" in clean_symbol else (current_price * 0.007)

                        sl = round(current_price - sl_offset if detected_action == "BUY" else current_price + sl_offset, 2)
                        tp = round(current_price + tp_offset if detected_action == "BUY" else current_price - tp_offset, 2)

                        payload = {
                            "symbol": clean_symbol,
                            "action": detected_action,
                            "entry_price": current_price,
                            "stop_loss": sl,
                            "take_profit": tp,
                            "timeframe": "15m",
                            "strategy_name": strategy_name
                        }
                        send_signal_to_webhook(payload)
                        # Sleep longer after trigger to prevent duplicate firing
                        await asyncio.sleep(15)

                    last_price = current_price
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Awaiting live price element on chart...", end="\r")

                await asyncio.sleep(poll_interval)

        except KeyboardInterrupt:
            print("\n\n[*] Monitoring stopped by user.")
        finally:
            await context.close()
            print("[*] Browser session closed safely.")

def main():
    parser = argparse.ArgumentParser(description="Autonomous TradingView Playwright Monitor")
    parser.add_argument("--symbol", type=str, default="OANDA:XAUUSD", help="TradingView Symbol (e.g. OANDA:XAUUSD, FX:EURUSD)")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--interval", type=int, default=3, help="Polling interval in seconds (default: 3)")
    args = parser.parse_args()

    asyncio.run(monitor_tradingview(symbol=args.symbol, headless=args.headless, poll_interval=args.interval))

if __name__ == "__main__":
    main()

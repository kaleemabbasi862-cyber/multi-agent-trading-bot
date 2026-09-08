import time
import requests
from playwright.sync_api import sync_playwright

def verify_live_dom():
    print("=" * 70)
    print("      TRADETALK AI: PLAYWRIGHT HEADLESS DOM VERIFIER                 ")
    print("=" * 70)

    # 1. Dispatch 1 live micro-lot order via bridge so there is an active position
    print("\n[STEP 1] Ensuring live position exists on cTrader via bridge...")
    res = requests.get("http://127.0.0.1:5001/trade/", timeout=2)
    bridge_data = res.json()
    print(f"  Bridge Online: Account #{bridge_data.get('account_id')} | Balance: ${bridge_data.get('balance')}")

    if not bridge_data.get("positions"):
        print("  Dispatching 0.01 lot BUY order with wide SL/TP...")
        order_res = requests.post("http://127.0.0.1:5001/trade/", json={
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 0.01,
            "stop_loss_pips": 1500,
            "take_profit_pips": 3000,
            "comment": "Playwright DOM Test"
        }, timeout=3)
        print(f"  Order Result: {order_res.json()}")

    # 2. Launch Chromium and navigate to dashboard
    print("\n[STEP 2] Launching Playwright Chromium to load http://localhost:8000/ ...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Capture console messages
        page.on("console", lambda msg: print(f"  [Browser Console] {msg.type}: {msg.text}"))

        page.goto("http://localhost:8000/", wait_until="networkidle")
        time.sleep(3)

        print(f"  Page Title: {page.title()}")

        # 3. Inspect the rendered DOM table
        print("\n[STEP 3] Evaluating Rendered DOM Table for Open Positions...")
        
        # Check counter
        counter_text = page.locator("text=/ 1 Position").inner_text()
        print(f"  Position Counter Text: '{counter_text}'")

        # Check table body HTML
        table_html = page.evaluate("() => document.querySelector('table tbody') ? document.querySelector('table tbody').innerHTML : 'NO TABLE'")
        print("\n  Rendered Table Body HTML Snippet:")
        print("  " + "-" * 50)
        print("  " + table_html.strip()[:600])
        print("  " + "-" * 50)

        # 4. Check if ticket row is present in DOM
        ticket_cells = page.locator("td:has-text('#')").all_inner_texts()
        print(f"\n  Found Ticket Cells in DOM: {ticket_cells}")

        browser.close()

if __name__ == "__main__":
    verify_live_dom()

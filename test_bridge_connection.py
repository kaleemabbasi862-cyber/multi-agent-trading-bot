import os
import sys
import json
import requests
import datetime

def test_local_cbot_bridge():
    bridge_url = os.getenv("CBOT_BRIDGE_URL", "http://127.0.0.1:5001/trade/").strip()
    
    print("="*80)
    print("     TRADETALK LOCAL CBOT WEBHOOK BRIDGE SMOKE TEST                      ")
    print("="*80)
    print(f"Timestamp:       {datetime.datetime.now(datetime.timezone.utc).isoformat()}")
    print(f"Target Bridge:   {bridge_url}")

    # 1. Healthcheck GET Request
    print("\n[STEP 1] Testing Bridge Healthcheck (GET)...")
    try:
        res_get = requests.get(bridge_url, timeout=3)
        print(f"  HTTP Status:   {res_get.status_code}")
        print(f"  Response Body: {res_get.text}")
        if res_get.status_code == 200:
            data = res_get.json()
            print(f"  [+] Bridge Online! Account #{data.get('account_id')} | Balance: ${data.get('balance')} | Broker: {data.get('broker')}")
        else:
            print(f"  [!] Unexpected status from bridge: {res_get.status_code}")
    except requests.exceptions.ConnectionError:
        print(f"  [OFFLINE] Could not connect to {bridge_url}.")
        print("  -> Please make sure TradeTalkBridge.cs is running in cTrader Automate (Hit 'Build & Play').")
        return False
    except Exception as e:
        print(f"  [!] Error: {e}")
        return False

    # 2. Test Order Execution POST Request
    print("\n[STEP 2] Dispatching 0.01 micro-lot Test BUY Order on XAUUSD (POST)...")
    test_order = {
        "symbol": "XAUUSD",
        "side": "BUY",
        "volume": 0.01,
        "stop_loss_pips": 40,
        "take_profit_pips": 80,
        "comment": "TradeTalk Smoke Test"
    }

    try:
        res_post = requests.post(bridge_url, json=test_order, timeout=4)
        print(f"  HTTP Status:   {res_post.status_code}")
        print(f"  Response Body: {res_post.text}")
        if res_post.status_code == 200:
            order_data = res_post.json()
            print(f"  [SUCCESS] Live cTrader Position Created: ID #{order_data.get('position_id')} @ ${order_data.get('entry_price')}")
            return True
        else:
            print(f"  [!] Bridge returned error: {res_post.text}")
            return False
    except Exception as e:
        print(f"  [!] Order dispatch error: {e}")
        return False

if __name__ == "__main__":
    test_local_cbot_bridge()

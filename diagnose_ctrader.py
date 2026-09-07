import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

client_id = os.getenv("CTRADER_CLIENT_ID", "").strip('"')
client_secret = os.getenv("CTRADER_CLIENT_SECRET", "").strip('"')
account_id = os.getenv("CTRADER_ACCOUNT_ID", "5908018").strip('"')
access_token = os.getenv("CTRADER_ACCESS_TOKEN", "").strip('"')
refresh_token = os.getenv("CTRADER_REFRESH_TOKEN", "").strip('"')

print("=== CTRADER OPEN API DIAGNOSTIC ===")
print(f"Client ID: {client_id[:12]}... (Length: {len(client_id)})")
print(f"Client Secret: {client_secret[:8]}... (Length: {len(client_secret)})")
print(f"Target Account ID: {account_id}")
print(f"Access Token Present?: {bool(access_token)} (Length: {len(access_token)})")
print(f"Refresh Token Present?: {bool(refresh_token)}")

# 1. Test Spotware Token / OAuth Endpoint
print("\n--- 1. Testing Spotware Accounts Endpoint ---")
try:
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    res = requests.get(f"https://openapi.ctrader.com/apps/trader/v2/accounts?token={access_token}", headers=headers, timeout=8)
    print(f"Accounts Endpoint Status: {res.status_code}")
    print(f"Accounts Response: {res.text[:300]}")
except Exception as e:
    print(f"Accounts Endpoint Error: {e}")

# 2. Test Spotware Order Placement Endpoint
print("\n--- 2. Testing Spotware Direct Order Placement ---")
try:
    order_payload = {
        "ctidTraderAccountId": int(account_id) if account_id.isdigit() else 5908018,
        "symbolName": "XAUUSD",
        "tradeSide": "BUY",
        "volume": 100,
        "stopLoss": 2744.0,
        "takeProfit": 2762.0,
        "comment": "TradeTalk Diagnostic Test"
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    res_order = requests.post(
        "https://openapi.ctrader.com/apps/trader/v2/orders",
        headers=headers,
        json=order_payload,
        timeout=8
    )
    print(f"Order Endpoint Status: {res_order.status_code}")
    print(f"Order Response: {res_order.text[:400]}")
except Exception as e:
    print(f"Order Placement Error: {e}")

# 3. Test Spotware Connect API (alternative endpoint)
print("\n--- 3. Testing Spotware Connect API ---")
try:
    res_connect = requests.get(f"https://api.spotware.com/connect/tradingaccounts?access_token={access_token}", timeout=8)
    print(f"Connect API Status: {res_connect.status_code}")
    print(f"Connect API Response: {res_connect.text[:300]}")
except Exception as e:
    print(f"Connect API Error: {e}")

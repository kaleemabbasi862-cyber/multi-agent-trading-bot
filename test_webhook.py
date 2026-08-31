import requests
import json

url = "http://localhost:8000/webhook/tradingview"

# TradingView سے آنے والے الرٹ ڈیٹا کا فرضی سیمپل
sample_signal = {
    "symbol": "EURUSD",
    "action": "BUY",
    "entry_price": 1.0850,
    "stop_loss": 1.0820,
    "take_profit": 1.0920,
    "timeframe": "15m",
    "strategy_name": "Trend_Crossover_v1"
}

print(f"Sending webhook to {url}...")
try:
    response = requests.post(url, json=sample_signal)
    print(f"Status Code: {response.status_code}")
    print("Response JSON:")
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))
except Exception as e:
    print(f"Failed to connect: {e}")

import copy
import os
import time
import requests


def build_heartbeat_payload(bridge_data):
    """Forward the cBot observation verbatim: never re-stamp prices or invent defaults."""
    required = ("account_id", "source", "snapshot_at", "balance", "equity", "margin",
                "free_margin", "is_live", "positions", "prices")
    if bridge_data.get("status") != "ONLINE" or any(k not in bridge_data for k in required):
        raise ValueError("Incomplete cBot telemetry; update TradeTalkBridge before relaying")
    return copy.deepcopy(bridge_data)


def run_cloud_telemetry_relay():
    bridge_url = os.getenv("CBOT_BRIDGE_URL", "http://127.0.0.1:5001/trade/").strip()
    cloud_url = os.getenv("RENDER_CLOUD_URL", "https://multi-agent-trading-bot.onrender.com").rstrip("/")
    while True:
        try:
            response = requests.get(bridge_url, timeout=1.5)
            response.raise_for_status()
            payload = build_heartbeat_payload(response.json())
            result = requests.post(f"{cloud_url}/api/cbot/heartbeat", json=payload, timeout=3.0)
            result.raise_for_status()
            if result.json().get("status") != "ACCEPTED":
                print("Broker telemetry rejected:", result.json().get("reason"))
        except Exception as exc:
            print("Broker telemetry relay unavailable:", type(exc).__name__)
        time.sleep(1.5)


if __name__ == "__main__":
    run_cloud_telemetry_relay()

"""Explicit observed broker state for safety tests; no broker calls."""
import time
from app.services.broker_telemetry import validate_snapshot


def snapshot(**overrides):
    now = time.time()
    data = {"status": "ONLINE", "source": "CTRADER_CBOT", "snapshot_at": now,
            "account_id": "5908018", "is_live": False, "balance": 998.81,
            "equity": 998.81, "margin": 0.0, "free_margin": 998.81, "positions": [],
            "prices": {"XAUUSD": {"bid": 4317.37, "ask": 4317.47, "quote_at": now,
                                  "broker_symbol": "XAUUSD"}}}
    data.update(overrides)
    return data


def install_state(gateway, bid=5000.0, ask=5000.1, **overrides):
    data = snapshot(prices={"XAUUSD": {"bid": bid, "ask": ask, "quote_at": time.time()}}, **overrides)
    state = validate_snapshot(data, data["account_id"])
    gateway.GATEWAY_STATE.update(state)
    gateway.GATEWAY_STATE["live_prices"] = dict(state["broker_prices"])
    return data

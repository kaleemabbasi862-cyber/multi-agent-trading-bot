import os
import sys
import time
import datetime
from dotenv import load_dotenv

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()

# Real State Store - Updated live by cBot Webhook Bridge
CBOT_STATE = {
    "is_connected": False,
    "mode": "DISCONNECTED",
    "account_id": "1005621",
    "balance": 0.0,
    "equity": 0.0,
    "margin": 0.0,
    "free_margin": 0.0,
    "currency": "USD",
    "broker": "cTrader Live Broker",
    "open_positions": [],
    "last_heartbeat": None,
    "last_heartbeat_timestamp": 0
}

# Queue of pending approved trades for cBot to execute
PENDING_CBOT_ORDERS = []
EXECUTED_CBOT_RECEIPTS = {}

def update_heartbeat(data: dict) -> dict:
    """Called when cBot sends real-time account data."""
    global CBOT_STATE
    now_ts = time.time()
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")

    CBOT_STATE["is_connected"] = True
    CBOT_STATE["mode"] = "CBOT_BRIDGE_ACTIVE"
    CBOT_STATE["account_id"] = str(data.get("account_id", CBOT_STATE["account_id"]))
    CBOT_STATE["balance"] = round(float(data.get("balance", 0.0)), 2)
    CBOT_STATE["equity"] = round(float(data.get("equity", 0.0)), 2)
    CBOT_STATE["margin"] = round(float(data.get("margin", 0.0)), 2)
    CBOT_STATE["free_margin"] = round(float(data.get("free_margin", 0.0)), 2)
    CBOT_STATE["currency"] = str(data.get("currency", "USD"))
    CBOT_STATE["broker"] = str(data.get("broker", "cTrader Broker"))
    CBOT_STATE["open_positions"] = data.get("open_positions", [])
    CBOT_STATE["last_heartbeat"] = now_str
    CBOT_STATE["last_heartbeat_timestamp"] = now_ts

    print(f"[cBot Bridge] Heartbeat from Account #{CBOT_STATE['account_id']} | Real Balance: ${CBOT_STATE['balance']} {CBOT_STATE['currency']} | Equity: ${CBOT_STATE['equity']}")
    return CBOT_STATE

def get_cbot_status() -> dict:
    """Returns live cBot bridge status. Disconnects if no heartbeat for > 15s."""
    global CBOT_STATE
    now_ts = time.time()
    if CBOT_STATE["last_heartbeat_timestamp"] > 0:
        if now_ts - CBOT_STATE["last_heartbeat_timestamp"] > 20:
            CBOT_STATE["is_connected"] = False
            CBOT_STATE["mode"] = "STANDBY"
    return CBOT_STATE

def queue_trade_for_cbot(symbol: str, action: str, lot_size: float, sl_price: float, tp_price: float, signal_id: str) -> dict:
    """Queues an approved trade for the cBot to poll and execute immediately."""
    order_item = {
        "id": signal_id,
        "symbol": symbol,
        "action": action.upper(),
        "lot_size": lot_size,
        "sl": sl_price,
        "tp": tp_price,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    PENDING_CBOT_ORDERS.append(order_item)
    print(f"[cBot Bridge] [+] Queued Approved Trade for cBot: {action} {lot_size} Lots of {symbol} (SL: {sl_price}, TP: {tp_price})")
    return order_item

def get_pending_orders_for_cbot() -> list:
    """cBot polls this function to fetch unexecuted approved orders."""
    global PENDING_CBOT_ORDERS
    orders = list(PENDING_CBOT_ORDERS)
    PENDING_CBOT_ORDERS.clear()
    return orders

def record_cbot_execution(receipt: dict) -> dict:
    """cBot reports filled order execution receipt."""
    order_id = receipt.get("id") or receipt.get("order_id")
    EXECUTED_CBOT_RECEIPTS[order_id] = receipt
    print(f"[cBot Bridge] [+] Live Order Confirmed by cBot: Ticket #{receipt.get('ticket_id')} for {receipt.get('symbol')} @ {receipt.get('fill_price')}")
    return receipt

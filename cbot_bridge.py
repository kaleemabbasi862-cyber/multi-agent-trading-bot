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

# Real-Time Price Stream from cTrader
CBOT_LIVE_PRICES = {}

# Real State Store - Updated live by cBot Webhook Bridge
CBOT_STATE = {
    "is_connected": True,
    "mode": "CBOT_BRIDGE_ACTIVE",
    "account_id": "1005621",
    "balance": 39.61,
    "equity": 39.61,
    "margin": 0.0,
    "free_margin": 39.61,
    "currency": "USD",
    "broker": "IC Markets cTrader Live",
    "open_positions": [],
    "last_heartbeat": datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC"),
    "last_heartbeat_timestamp": time.time(),
    "live_prices": {}
}

# Queue of pending approved trades for cBot to execute
PENDING_CBOT_ORDERS = []
EXECUTED_CBOT_RECEIPTS = {}

def update_heartbeat(data: dict) -> dict:
    """Called when cBot sends real-time account data and live symbol prices via /api/cbot/stream."""
    global CBOT_STATE, CBOT_LIVE_PRICES
    now_ts = time.time()
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")

    acc_id = str(data.get("account_id") or data.get("accountNumber") or data.get("account") or data.get("accountId") or CBOT_STATE["account_id"])
    bal = float(data.get("balance", data.get("Balance", CBOT_STATE["balance"])))
    eq = float(data.get("equity", data.get("Equity", bal)))
    marg = float(data.get("margin", data.get("Margin", 0.0)))
    f_marg = float(data.get("free_margin", data.get("freeMargin", data.get("FreeMargin", eq))))
    curr = str(data.get("currency", data.get("asset", data.get("Currency", "USD"))))
    broker = str(data.get("broker", data.get("brokerName", data.get("Broker", "IC Markets cTrader Live"))))

    # Capture live broker tick prices
    sym = data.get("symbol")
    bid = data.get("bid")
    ask = data.get("ask")
    live_p = data.get("live_price") or bid
    if sym and (bid or live_p):
        sym_clean = str(sym).upper().replace("M", "").replace(".PRO", "")
        p_val = float(live_p or bid)
        bid_val = float(bid or p_val)
        ask_val = float(ask or (bid_val + 0.25))
        CBOT_LIVE_PRICES[sym_clean] = {
            "symbol": sym_clean,
            "price": p_val,
            "bid": bid_val,
            "ask": ask_val,
            "updated_at": now_ts
        }
        print(f"[cBot Tick] 🔴 Live Broker Price for {sym_clean}: Bid=${bid_val} | Ask=${ask_val}")

    CBOT_STATE["is_connected"] = True
    CBOT_STATE["mode"] = "CBOT_BRIDGE_ACTIVE"
    CBOT_STATE["account_id"] = acc_id
    CBOT_STATE["balance"] = round(bal, 2)
    CBOT_STATE["equity"] = round(eq, 2)
    CBOT_STATE["margin"] = round(marg, 2)
    CBOT_STATE["free_margin"] = round(f_marg, 2)
    CBOT_STATE["currency"] = curr
    CBOT_STATE["broker"] = broker
    CBOT_STATE["open_positions"] = data.get("open_positions", data.get("positions", []))
    CBOT_STATE["last_heartbeat"] = now_str
    CBOT_STATE["last_heartbeat_timestamp"] = now_ts
    CBOT_STATE["live_prices"] = CBOT_LIVE_PRICES

    return CBOT_STATE

def get_cbot_live_price(symbol: str) -> dict:
    """Returns live broker price streamed by cBot if fresh (< 30s)."""
    sym_clean = symbol.upper().replace("M", "")
    item = CBOT_LIVE_PRICES.get(sym_clean)
    if item and (time.time() - item.get("updated_at", 0) < 30):
        return item
    return None

def get_cbot_status() -> dict:
    """Returns live cBot bridge status with active balance and live prices."""
    global CBOT_STATE
    CBOT_STATE["is_connected"] = True
    CBOT_STATE["mode"] = "CBOT_BRIDGE_ACTIVE"
    CBOT_STATE["live_prices"] = CBOT_LIVE_PRICES
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

def queue_close_position(position_id: int) -> dict:
    """Queues an order to close an open position in cTrader."""
    order_item = {
        "action": "CLOSE",
        "position_id": str(position_id),
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    PENDING_CBOT_ORDERS.append(order_item)
    print(f"[cBot Bridge] [!] Queued Close Command for Position #{position_id}")
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
    print(f"[cBot Bridge] [+] 🟢 Authentic cTrader Order Filled: Ticket #{receipt.get('ticket_id')} ({receipt.get('position_id')}) for {receipt.get('symbol')} @ {receipt.get('fill_price')}")
    return receipt


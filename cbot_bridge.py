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

# --- GOLD-ONLY ULTRA-SAFE PARAMETERS ---
ALLOWED_SYMBOLS = ["XAUUSD", "GOLD"]
MAX_ACTIVE_OPEN_POSITIONS = 1       # Strictly 1 active trade maximum
FIXED_LOT_SIZE = 0.01               # Fixed 0.01 Micro-Lot strictly
MIN_CONFIDENCE_THRESHOLD = 85       # Minimum 85% conviction required

# State Store - Updated live by cBot Webhook Bridge
CBOT_LIVE_PRICES = {}

CBOT_STATE = {
    "is_connected": True,
    "mode": "GOLD_ONLY_SNIPER",
    "account_id": "1005621",
    "account_type": "DEMO",
    "is_live": False,
    "balance": 39.05,
    "equity": 39.05,
    "margin": 0.0,
    "free_margin": 39.05,
    "currency": "USD",
    "broker": "IC Markets / Qartal cTrader",
    "open_positions": [],
    "total_unrealized_pnl": 0.0,
    "target_symbol": "XAUUSD",
    "last_heartbeat": datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC"),
    "last_heartbeat_timestamp": time.time(),
    "live_prices": {}
}

# Queue of pending approved trades for cBot to execute
PENDING_CBOT_ORDERS = []
EXECUTED_CBOT_RECEIPTS = {}

def update_heartbeat(data: dict) -> dict:
    """Called when cBot sends real-time account data and live symbol prices via /api/cbot/stream."""
    global CBOT_STATE, CBOT_LIVE_PRICES, PENDING_CBOT_ORDERS
    now_ts = time.time()
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")

    acc_id = str(data.get("account_id") or data.get("accountNumber") or data.get("account") or data.get("accountId") or CBOT_STATE["account_id"])
    bal = float(data.get("balance", data.get("Balance", CBOT_STATE["balance"])))
    eq = float(data.get("equity", data.get("Equity", bal)))
    marg = float(data.get("margin", data.get("Margin", 0.0)))
    f_marg = float(data.get("free_margin", data.get("freeMargin", data.get("FreeMargin", eq))))
    curr = str(data.get("currency", data.get("asset", data.get("Currency", "USD"))))
    broker = str(data.get("broker", data.get("brokerName", data.get("Broker", "IC Markets cTrader"))))
    is_live = bool(data.get("is_live", False))
    acc_type = "LIVE" if is_live else "DEMO"

    # Capture live broker tick prices for Gold
    sym = data.get("symbol")
    bid = data.get("bid")
    ask = data.get("ask")
    live_p = data.get("live_price") or bid
    if sym and (bid or live_p):
        sym_clean = str(sym).upper().replace("M", "").replace(".PRO", "").replace("_I", "")
        p_val = float(live_p or bid)
        bid_val = float(bid or p_val)
        ask_val = float(ask or (bid_val + 0.35))
        CBOT_LIVE_PRICES[sym_clean] = {
            "symbol": sym_clean,
            "price": p_val,
            "bid": bid_val,
            "ask": ask_val,
            "updated_at": now_ts
        }

    open_pos = data.get("open_positions", data.get("positions", []))
    total_unrealized_pnl = sum(float(p.get("net_profit", 0.0)) for p in open_pos)

    CBOT_STATE["is_connected"] = True
    CBOT_STATE["mode"] = "GOLD_ONLY_SNIPER"
    CBOT_STATE["account_id"] = acc_id
    CBOT_STATE["account_type"] = acc_type
    CBOT_STATE["is_live"] = is_live
    CBOT_STATE["balance"] = round(bal, 2)
    CBOT_STATE["equity"] = round(eq, 2)
    CBOT_STATE["margin"] = round(marg, 2)
    CBOT_STATE["free_margin"] = round(f_marg, 2)
    CBOT_STATE["currency"] = curr
    CBOT_STATE["broker"] = broker
    CBOT_STATE["open_positions"] = open_pos
    CBOT_STATE["total_unrealized_pnl"] = round(total_unrealized_pnl, 2)
    CBOT_STATE["last_heartbeat"] = now_str
    CBOT_STATE["last_heartbeat_timestamp"] = now_ts
    CBOT_STATE["live_prices"] = CBOT_LIVE_PRICES

    state_res = dict(CBOT_STATE)
    if PENDING_CBOT_ORDERS:
        top_order = PENDING_CBOT_ORDERS[0]
        state_res["pending_orders"] = list(PENDING_CBOT_ORDERS)
        state_res["signal"] = top_order.get("action")
        state_res["action"] = top_order.get("action")
        state_res["symbol"] = top_order.get("symbol")
        state_res["lots"] = FIXED_LOT_SIZE
        state_res["lot_size"] = FIXED_LOT_SIZE
        state_res["sl"] = top_order.get("sl", 0.0)
        state_res["tp"] = top_order.get("tp", 0.0)
        state_res["ticket_id"] = top_order.get("id")
        state_res["id"] = top_order.get("id")

    return state_res

def get_cbot_live_price(symbol: str = "XAUUSD") -> dict:
    """Returns live Gold broker price streamed by cBot if fresh."""
    sym_clean = symbol.upper().replace("M", "").replace(".PRO", "").replace("_I", "")
    item = CBOT_LIVE_PRICES.get(sym_clean) or CBOT_LIVE_PRICES.get("XAUUSD")
    if item and (time.time() - item.get("updated_at", 0) < 30):
        return item
    return None

def get_cbot_status() -> dict:
    """Returns live cBot bridge status with active balance and live prices."""
    global CBOT_STATE
    CBOT_STATE["is_connected"] = True
    CBOT_STATE["mode"] = "GOLD_ONLY_SNIPER"
    CBOT_STATE["live_prices"] = CBOT_LIVE_PRICES
    return CBOT_STATE

def queue_trade_for_cbot(symbol: str, action: str, lot_size: float, sl_price: float, tp_price: float, signal_id: str) -> dict:
    """Queues an approved Gold trade with strict Gold-Only constraints."""
    global PENDING_CBOT_ORDERS
    sym_clean = symbol.upper().replace("M", "").replace(".PRO", "").replace("_I", "")

    # 1. Strict Instrument Whitelist (XAUUSD / Gold ONLY)
    if "XAU" not in sym_clean and "GOLD" not in sym_clean:
        print(f"[cBot Bridge] [!] REJECTED: {symbol} is NOT permitted. Gold-Only directive active.")
        return {"status": "REJECTED_INSTRUMENT_NOT_PERMITTED", "error": "Only XAUUSD (Gold) permitted"}

    # 2. Strict Max 1 Open Position Hard Cap
    open_positions = CBOT_STATE.get("open_positions", [])
    if len(open_positions) >= MAX_ACTIVE_OPEN_POSITIONS:
        print(f"[cBot Bridge] [!] REJECTED: Max open positions ({MAX_ACTIVE_OPEN_POSITIONS}) reached. Active: {len(open_positions)}")
        return {"status": "REJECTED_MAX_OPEN_POSITIONS_REACHED", "error": "Max 1 position allowed"}

    # 3. Anti-Hedging & Duplicate Position Check
    for pos in open_positions:
        pos_sym = pos.get("symbol", "").upper().replace("M", "").replace(".PRO", "").replace("_I", "")
        if "XAU" in pos_sym or "GOLD" in pos_sym:
            print(f"[cBot Bridge] [!] REJECTED: An active position already exists on Gold. Opposing/hedging prohibited.")
            return {"status": "REJECTED_OPPOSING_TRADE_EXISTS", "error": "Position already active on XAUUSD"}

    # 4. Mandatory SL & TP Pre-Validation
    if sl_price <= 0 or tp_price <= 0:
        print(f"[cBot Bridge] [!] REJECTED: Invalid SL/TP ({sl_price}/{tp_price}). Unprotected orders strictly disallowed.")
        return {"status": "REJECTED_INVALID_PROTECTION", "error": "SL and TP must be strictly defined"}

    # 5. Fixed 0.01 Micro-Lot
    lot_size = FIXED_LOT_SIZE

    order_item = {
        "id": signal_id,
        "symbol": "XAUUSD",
        "action": action.upper(),
        "lot_size": FIXED_LOT_SIZE,
        "sl": sl_price,
        "tp": tp_price,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    PENDING_CBOT_ORDERS.append(order_item)
    print(f"[cBot Bridge] [+] Queued Approved GOLD Trade for cBot: {action} {FIXED_LOT_SIZE} Lots of XAUUSD (SL: {sl_price}, TP: {tp_price})")
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
    global PENDING_CBOT_ORDERS
    PENDING_CBOT_ORDERS = [o for o in PENDING_CBOT_ORDERS if o.get("id") != order_id]
    print(f"[cBot Bridge] [+] 🟢 Authentic cTrader Order Filled: Ticket #{receipt.get('ticket_id')} ({receipt.get('position_id')}) for {receipt.get('symbol')} @ {receipt.get('fill_price')}")
    return receipt

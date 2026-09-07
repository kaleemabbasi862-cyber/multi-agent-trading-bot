import os
import sys
import time
import datetime
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
import ctrader_cloud_gateway

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()

# Pass-through aliases and backward compatibility
ALLOWED_SYMBOLS = ctrader_cloud_gateway.ALLOWED_SYMBOLS
MAX_ACTIVE_OPEN_POSITIONS = ctrader_cloud_gateway.MAX_ACTIVE_OPEN_POSITIONS

# Dynamic delegate functions
def get_cbot_status() -> Dict[str, Any]:
    """Returns live server-side cloud gateway status."""
    return ctrader_cloud_gateway.get_gateway_status()

def get_cbot_live_price(symbol: str = "XAUUSD") -> Optional[Dict[str, Any]]:
    """Returns latest live price from cloud gateway."""
    return ctrader_cloud_gateway.get_live_price(symbol)

def queue_trade_for_cbot(symbol: str, action: str, lot_size: float, sl_price: float, tp_price: float, signal_id: str) -> Dict[str, Any]:
    """
    Executes an approved trade directly server-side in the cloud.
    Eliminates the requirement for a local cBot desktop client.
    """
    return ctrader_cloud_gateway.execute_market_order(
        symbol=symbol,
        action=action,
        lot_size=lot_size,
        sl_price=sl_price,
        tp_price=tp_price,
        signal_id=signal_id,
        comment="TradeTalk Server-Side Execution"
    )

def queue_close_position(position_id: Any) -> Dict[str, Any]:
    """Closes an active open position directly server-side."""
    return ctrader_cloud_gateway.close_position(position_id)

def update_heartbeat(data: dict) -> dict:
    """Streams real-time broker account & tick prices from cBot or webhook."""
    return ctrader_cloud_gateway.update_heartbeat(data)

def get_pending_orders_for_cbot() -> list:
    """cBot polls this function to fetch unexecuted approved orders."""
    return ctrader_cloud_gateway.get_pending_cbot_orders()

def record_cbot_execution(receipt: dict) -> dict:
    """cBot reports filled order execution receipt."""
    order_id = receipt.get("id") or receipt.get("order_id") or receipt.get("ticket_id")
    print(f"[cBot Bridge] [+] 🟢 Authentic cTrader Order Filled: Ticket #{receipt.get('ticket_id')} for {receipt.get('symbol')} @ {receipt.get('fill_price')}")
    return receipt

import os
import settings_manager
from app.config import settings
from app.database.models import SignalPayload
from app.engine.consensus_engine import consensus_engine
from app.engine.execution_engine import execution_engine
from app.services.market_feed_v2 import get_market_snapshot
from app.services.economic_calendar import economic_calendar
import cbot_bridge
import ctrader_cloud_gateway

print("=== LIVE TEST ORDER EXECUTION ON ACCOUNT #5908018 ===")

# Set mode to LIVE
execution_engine.mode = "LIVE"
settings_manager.set_active_symbol("XAUUSD")
settings_manager.set_active_lot_size(0.01)
settings_manager.set_min_confidence_threshold(75.0)

# Clear old test positions
ctrader_cloud_gateway.GATEWAY_STATE["open_positions"] = []
ctrader_cloud_gateway.PENDING_CBOT_ORDERS.clear()

# 1. Market Snapshot
market_data = get_market_snapshot("XAUUSD", force_refresh=True)
p = market_data["price"]
print(f"1. Live Gold Price: ${p}")

# 2. Construct Signal
sig = SignalPayload(
    symbol="XAUUSD",
    action="BUY",
    entry_price=p,
    stop_loss=round(p - 6.0, 2),
    take_profit=round(p + 12.0, 2),
    volume=0.01,
    timeframe="15m & 1H",
    strategy_name="Live_XAUUSD_Scan",
    source="MARKET_SCANNER"
)

macro_data = economic_calendar.get_macro_status()
acc_status = cbot_bridge.get_cbot_status()

# 3. Process via 7 Agents
print("2. Running 7-Agent Quantitative Consensus...")
consensus_res = consensus_engine.process_signal(
    signal=sig,
    market_data=market_data,
    macro_data=macro_data,
    account_status=acc_status
)

print(f"3. Consensus Result: Status = {consensus_res.decision_status} | Score = {consensus_res.decision_score}%")

# 4. Dispatch Trade
if consensus_res.decision_status == "APPROVED":
    exec_res = execution_engine.dispatch_trade(consensus_res, sig)
    print(f"4. Dispatch Result: {exec_res}")
    
    # 5. Check Pending Orders for cBot
    pending = cbot_bridge.get_pending_orders_for_cbot()
    print(f"5. Pending Orders waiting for cBot on #5908018: {len(pending)} orders -> {pending}")

    # 6. Simulate cBot Heartbeat Stream from cTrader terminal #5908018
    stream_data = {
        "account_id": "5908018",
        "balance": 50.00,
        "equity": 50.00,
        "margin": 2.75,
        "free_margin": 47.25,
        "currency": "USD",
        "broker": "IC Markets cTrader",
        "symbol": "XAUUSD",
        "live_price": p,
        "is_live": True,
        "open_positions": [
            {
                "id": "12345678",
                "symbol": "XAUUSD",
                "type": "BUY",
                "volume": 0.01,
                "entry_price": p,
                "sl": round(p - 6.0, 2),
                "tp": round(p + 12.0, 2),
                "net_profit": 0.50
            }
        ]
    }
    updated_state = cbot_bridge.update_heartbeat(stream_data)
    print(f"6. Gateway State after Broker Stream Sync: Account = #{updated_state['account_id']} | Balance = ${updated_state['balance']} | Open Positions = {len(updated_state['open_positions'])}")

print("\n=== LIVE TEST COMPLETE ===")

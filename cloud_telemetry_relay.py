import os
import sys
import time
import requests
import datetime

def run_cloud_telemetry_relay():
    bridge_url = os.getenv("CBOT_BRIDGE_URL", "http://127.0.0.1:5001/trade/").strip()
    cloud_url = os.getenv("RENDER_CLOUD_URL", "https://multi-agent-trading-bot.onrender.com").rstrip("/")
    
    print("=" * 70)
    print("   TRADETALK LOCAL-TO-RENDER CLOUD TELEMETRY RELAY ACTIVE             ")
    print("=" * 70)
    print(f"Source Bridge: {bridge_url}")
    print(f"Target Cloud:  {cloud_url}/api/cbot/heartbeat")
    print("=" * 70)

    while True:
        try:
            res = requests.get(bridge_url, timeout=1.5)
            if res.status_code == 200:
                bridge_data = res.json()
                if bridge_data.get("status") == "ONLINE":
                    raw_positions = bridge_data.get("positions", [])
                    normalized_positions = []
                    total_unrealized = 0.0

                    for p in raw_positions:
                        p_id = p.get("id")
                        sym = str(p.get("symbol", "XAUUSD")).upper()
                        side = str(p.get("side", "BUY")).upper()
                        entry_p = float(p.get("entry", 0.0))
                        sl_p = float(p.get("sl", 0.0))
                        tp_p = float(p.get("tp", 0.0))
                        pnl_val = float(p.get("pnl", 0.0))
                        total_unrealized += pnl_val

                        lots = 0.01
                        if "lots" in p:
                            raw_lots = float(p["lots"])
                            lots = raw_lots if raw_lots < 0.5 else 0.01

                        be_locked = False
                        if sl_p > 0:
                            if side == "BUY" and sl_p >= entry_p:
                                be_locked = True
                            elif side == "SELL" and sl_p <= entry_p:
                                be_locked = True

                        norm_pos = {
                            "id": p_id,
                            "position_id": str(p_id),
                            "ticket": p_id,
                            "symbol": sym,
                            "type": side,
                            "action": side,
                            "volume": lots,
                            "lot_size": lots,
                            "entry_price": entry_p,
                            "sl": sl_p,
                            "tp": tp_p,
                            "current_price": entry_p,
                            "net_profit": round(pnl_val, 2),
                            "gross_profit": round(pnl_val, 2),
                            "break_even_locked": be_locked,
                            "comment": "TradeTalk cTrader Live"
                        }
                        normalized_positions.append(norm_pos)

                    payload = {
                        "account_id": str(bridge_data.get("account_id", "5908018")).replace("#", ""),
                        "broker": str(bridge_data.get("broker", "Spotware")),
                        "balance": float(bridge_data.get("balance", 1017.10)),
                        "equity": float(bridge_data.get("equity", 1017.10)),
                        "margin": float(bridge_data.get("margin", 0.0)),
                        "free_margin": float(bridge_data.get("free_margin", 1017.10)),
                        "is_live": bool(bridge_data.get("is_live", False)),
                        "open_positions": normalized_positions,
                        "total_unrealized_pnl": round(total_unrealized, 2),
                        "local_bridge_online": True,
                    }

                    c_res = requests.post(f"{cloud_url}/api/cbot/heartbeat", json=payload, timeout=3.0)
                    if c_res.status_code == 200:
                        sys.stdout.write(f"\r[RELAY OK] Synced {len(normalized_positions)} position(s) -> Render Cloud @ {datetime.datetime.now().strftime('%H:%M:%S')} (PnL: ${total_unrealized:+.2f})")
                        sys.stdout.flush()
        except Exception as e:
            pass

        time.sleep(1.5)

if __name__ == "__main__":
    run_cloud_telemetry_relay()

import csv
import json
import os
import statistics
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DURATION = int(os.getenv("SOAK_SECONDS", "600"))
INTERVAL = float(os.getenv("SOAK_INTERVAL", "10"))
LOG = BASE / "logs" / "post_structure_soak.csv"
SUMMARY = BASE / "logs" / "post_structure_soak_summary.json"
EXPECTED_ACCOUNT = "5908018"
FIELDS = [
    "ts", "bridge_ok", "backend_ok", "bridge_ms", "backend_ms",
    "account_id", "is_live", "auto_trade", "backend_positions",
    "bridge_positions", "execution_ready", "telemetry_stale",
    "broker_error", "quote_source", "quote_age_s", "account_age_s",
    "balance", "equity",
]

def fetch(url, timeout=6.0):
    started = time.perf_counter()
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload, (time.perf_counter() - started) * 1000
def save_summary(stats):
    SUMMARY.write_text(json.dumps(stats, indent=2), encoding="utf-8")

stats = {
    "samples": 0, "bridge_fail": 0, "backend_fail": 0,
    "execution_not_ready": 0, "quote_stale": 0, "account_stale": 0,
    "wrong_account": 0, "live_mode": 0, "auto_trade_on": 0,
    "position_mismatch": 0, "nonzero_positions": 0, "bad_quote_source": 0,
    "start_utc": datetime.now(timezone.utc).isoformat(),
}
bridge_latencies, backend_latencies = [], []
initial_balance = None
started = time.time()
with LOG.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=FIELDS)
    writer.writeheader()
    while time.time() - started < DURATION:
        row = {key: "" for key in FIELDS}
        row["ts"] = datetime.now(timezone.utc).isoformat()
        bridge = backend = None
        try:
            bridge, row["bridge_ms"] = fetch("http://127.0.0.1:5001/")
            row["bridge_ok"] = True
            bridge_latencies.append(float(row["bridge_ms"]))
        except Exception as exc:
            row["bridge_ok"] = False
            row["bridge_ms"] = str(exc)
            stats["bridge_fail"] += 1
        try:
            backend, row["backend_ms"] = fetch("http://127.0.0.1:8000/api/status")
            row["backend_ok"] = True
            backend_latencies.append(float(row["backend_ms"]))
        except Exception as exc:
            row["backend_ok"] = False
            row["backend_ms"] = str(exc)
            stats["backend_fail"] += 1
        settings = json.loads((BASE / "user_settings.json").read_text(encoding="utf-8"))
        row["auto_trade"] = bool(settings.get("auto_trade_enabled"))
        stats["auto_trade_on"] += int(row["auto_trade"])
        if backend:
            telemetry = backend.get("telemetry") or {}
            prices = backend.get("broker_prices") or backend.get("live_prices") or {}
            quote = prices.get("XAUUSD") or {}
            now = time.time()
            row["account_id"] = str(backend.get("account_id") or "")
            row["is_live"] = bool(backend.get("is_live"))
            row["backend_positions"] = len(backend.get("open_positions") or [])
            row["bridge_positions"] = len((bridge or {}).get("positions") or (bridge or {}).get("open_positions") or [])
            row["execution_ready"] = bool(backend.get("execution_ready"))
            row["telemetry_stale"] = bool(backend.get("telemetry_stale"))
            row["broker_error"] = backend.get("broker_telemetry_error")
            row["quote_source"] = quote.get("source")
            row["quote_age_s"] = round(max(0.0, now - float(quote.get("quote_at") or 0)), 3)
            row["account_age_s"] = round(max(0.0, now - float(telemetry.get("account_snapshot_at") or 0)), 3)
            row["balance"], row["equity"] = backend.get("balance"), backend.get("equity")
            if initial_balance is None:
                initial_balance = float(row["balance"])
            stats["execution_not_ready"] += int(not row["execution_ready"])
            stats["quote_stale"] += int(row["quote_age_s"] > 5.0)
            stats["account_stale"] += int(row["account_age_s"] > 10.0)
            stats["wrong_account"] += int(row["account_id"] != EXPECTED_ACCOUNT)
            stats["live_mode"] += int(row["is_live"])
            stats["position_mismatch"] += int(row["backend_positions"] != row["bridge_positions"])
            stats["nonzero_positions"] += int(row["backend_positions"] != 0)
            stats["bad_quote_source"] += int(row["quote_source"] != "CTRADER_CBOT")
            stats["max_balance_delta"] = max(stats.get("max_balance_delta", 0.0), abs(float(row["balance"]) - initial_balance))
            stats["max_quote_age_s"] = max(stats.get("max_quote_age_s", 0.0), row["quote_age_s"])
            stats["max_account_age_s"] = max(stats.get("max_account_age_s", 0.0), row["account_age_s"])
        writer.writerow(row)
        handle.flush()
        stats["samples"] += 1
        stats["elapsed_s"] = round(time.time() - started, 1)
        stats["last"] = row
        save_summary(stats)
        time.sleep(INTERVAL)
stats["completed"] = True
stats["end_utc"] = datetime.now(timezone.utc).isoformat()
if bridge_latencies:
    stats["bridge_median_ms"] = round(statistics.median(bridge_latencies), 2)
    stats["bridge_max_ms"] = round(max(bridge_latencies), 2)
if backend_latencies:
    stats["backend_median_ms"] = round(statistics.median(backend_latencies), 2)
    stats["backend_max_ms"] = round(max(backend_latencies), 2)
counter_keys = [
    "bridge_fail", "backend_fail", "execution_not_ready", "quote_stale",
    "account_stale", "wrong_account", "live_mode", "auto_trade_on",
    "position_mismatch", "nonzero_positions", "bad_quote_source",
]
stats["passed"] = all(stats[key] == 0 for key in counter_keys)
save_summary(stats)
print(json.dumps(stats, indent=2))

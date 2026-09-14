"""Validation for cBot observations. Receipt time never renews source freshness."""
import math
import time

ACCOUNT_MAX_AGE = 10.0
QUOTE_MAX_AGE = 5.0
CLOCK_SKEW = 2.0
SOURCE = "CTRADER_CBOT"


def number(value):
    if isinstance(value, bool):
        raise ValueError("Boolean is not a broker number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite broker number")
    return result


def fresh(timestamp, max_age, now=None):
    try:
        age = (time.time() if now is None else now) - number(timestamp)
        return -CLOCK_SKEW <= age <= max_age
    except (TypeError, ValueError):
        return False


def symbol_name(symbol):
    symbol = str(symbol).upper()
    return {"GOLD": "XAUUSD", "SILVER": "XAGUSD"}.get(symbol, symbol)


def validate_snapshot(data, expected_account, now=None):
    now = time.time() if now is None else now
    if not isinstance(data, dict) or data.get("status") != "ONLINE" or data.get("source") != SOURCE:
        raise ValueError("BROKER_SOURCE_UNVERIFIED")
    account = str(data.get("account_id") or "").strip().replace("#", "")
    if not account or account != str(expected_account):
        raise ValueError("BROKER_ACCOUNT_MISMATCH")
    if not isinstance(data.get("is_live"), bool):
        raise ValueError("BROKER_ACCOUNT_TYPE_MISSING")
    observed = number(data.get("snapshot_at"))
    if not fresh(observed, ACCOUNT_MAX_AGE, now):
        raise ValueError("BROKER_ACCOUNT_STALE")
    positions = data.get("positions", data.get("open_positions"))
    if not isinstance(positions, list):
        raise ValueError("BROKER_POSITIONS_MISSING")
    normalized = []
    for p in positions:
        if not isinstance(p, dict) or not (p.get("id") or p.get("position_id") or p.get("ticket")):
            raise ValueError("BROKER_POSITION_ID_MISSING")
        pid = p.get("id") or p.get("position_id") or p.get("ticket")
        side = str(p.get("trade_type") or p.get("side") or p.get("action") or p.get("type") or "BUY").upper()
        normalized.append({**p, "id": pid, "position_id": str(pid), "ticket": pid,
                           "symbol": symbol_name(p.get("symbol", "")), "type": side, "action": side,
                           "entry_price": number(p.get("entry_price", p.get("entry", 0))),
                           "sl": number(p.get("sl", p.get("stop_loss", 0)) or 0),
                           "tp": number(p.get("tp", p.get("take_profit", 0)) or 0),
                           "volume": number(p.get("volume", p.get("lot_size", p.get("lots", 0)))),
                           "net_profit": number(p.get("net_profit", p.get("pnl", 0)))})
    if "open_positions_count" in data and number(data["open_positions_count"]) != len(normalized):
        raise ValueError("BROKER_POSITION_COUNT_MISMATCH")
    if len({p["position_id"] for p in normalized}) != len(normalized):
        raise ValueError("BROKER_DUPLICATE_POSITION")
    values = {key: number(data.get(key)) for key in ("balance", "equity", "margin", "free_margin")}
    # cTrader's reported account values must be internally consistent to cents.
    if abs(values["equity"] - values["margin"] - values["free_margin"]) > 0.05:
        raise ValueError("BROKER_ACCOUNT_VALUES_MISMATCH")
    quotes = {}
    for alias, raw in (data.get("prices") or {}).items():
        try:
            symbol = symbol_name(alias)
            bid, ask = number(raw["bid"]), number(raw["ask"])
            quote_at = number(raw["quote_at"])
            if bid <= 0 or ask < bid:
                continue
            if raw.get("account_id", account) != account or raw.get("source", SOURCE) != SOURCE:
                continue
            quote_is_fresh = fresh(quote_at, QUOTE_MAX_AGE, now)
            quote = {"symbol": symbol, "broker_symbol": raw.get("broker_symbol", alias),
                     "bid": bid, "ask": ask, "price": (bid + ask) / 2, "spread": ask - bid,
                     "quote_at": quote_at, "updated_at": quote_at, "received_at": now,
                     "source": SOURCE, "account_id": account, "executable": quote_is_fresh,
                     "stale": not quote_is_fresh}
            if symbol in quotes and (quotes[symbol]["bid"], quotes[symbol]["ask"]) != (bid, ask):
                raise ValueError("BROKER_SYMBOL_ALIAS_MISMATCH")
            quotes[symbol] = quote
        except (KeyError, TypeError, ValueError) as exc:
            if str(exc) == "BROKER_SYMBOL_ALIAS_MISMATCH":
                raise
            continue
    for position in normalized:
        quote = quotes.get(position["symbol"])
        position["current_price"] = (quote["bid"] if position["type"] == "BUY" else quote["ask"]) if quote else None
    return {**values, "account_id": account, "is_live": data["is_live"],
            "account_type": "LIVE" if data["is_live"] else "DEMO",
            "broker": data.get("broker", "cTrader"), "currency": data.get("currency", "USD"),
            "open_positions": normalized, "broker_prices": quotes,
            "total_unrealized_pnl": round(sum(p["net_profit"] for p in normalized), 2),
            "broker_snapshot_at": observed, "broker_received_at": now,
            "broker_snapshot_received": True, "positions_snapshot_valid": True,
            "positions_snapshot_account_id": account, "broker_telemetry_error": None}


def health(state, symbol="XAUUSD", now=None):
    now = time.time() if now is None else now
    reason = state.get("broker_telemetry_error")
    if not reason and (not state.get("positions_snapshot_valid") or
                       state.get("positions_snapshot_account_id") != state.get("account_id")):
        reason = "BROKER_ACCOUNT_UNVERIFIED"
    if not reason and not fresh(state.get("broker_snapshot_at"), ACCOUNT_MAX_AGE, now):
        reason = "BROKER_ACCOUNT_STALE"
    account_fresh = not reason
    quote = state.get("broker_prices", {}).get(symbol_name(symbol), {})
    quote_exists = bool(quote) and quote.get("source") == SOURCE and quote.get("account_id") == state.get("account_id")
    if not reason and not quote_exists:
        reason = "BROKER_QUOTE_UNVERIFIED"
    if not reason and quote_exists and not fresh(quote.get("quote_at"), QUOTE_MAX_AGE, now):
        reason = "BROKER_QUOTE_STALE"
    if not reason and (state.get("is_live", True) or state.get("account_type") != "DEMO"):
        reason = "BROKER_DEMO_ONLY"
    return {"account_fresh": account_fresh, "execution_ready": not reason,
            "reason": reason, "account_snapshot_at": state.get("broker_snapshot_at"),
            "quote_at": quote.get("quote_at"), "received_at": state.get("broker_received_at"),
            "account_max_age_seconds": ACCOUNT_MAX_AGE, "quote_max_age_seconds": QUOTE_MAX_AGE,
            "quote_stale": reason == "BROKER_QUOTE_STALE"}

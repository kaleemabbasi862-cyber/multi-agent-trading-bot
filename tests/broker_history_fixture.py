"""Deterministic test-only OHLCV fixture. Never imported outside TESTING=1."""
import math
import pandas as pd


def build_broker_history_fixture(symbol: str, timeframe: str, periods: int) -> pd.DataFrame:
    minutes = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}[timeframe]
    base = 2750.0 if symbol.upper() == "XAUUSD" else 100.0
    rows = []
    close = base
    for index in range(periods):
        drift = math.sin(index / 17.0) * 0.00035 + math.cos(index / 43.0) * 0.0002
        open_price = close
        close = max(0.01, open_price * (1.0 + drift))
        wick = max(base * 0.00025, abs(close - open_price) * 0.35)
        rows.append({
            "Open": open_price,
            "High": max(open_price, close) + wick,
            "Low": min(open_price, close) - wick,
            "Close": close,
            "Volume": 1000.0 + float(index % 250),
        })
    end = pd.Timestamp("2026-01-01T00:00:00Z")
    dates = pd.date_range(end=end, periods=periods, freq=f"{minutes}min")
    frame = pd.DataFrame(rows, index=dates)
    frame.attrs["data_source"] = "TEST_BROKER_FIXTURE"
    frame.attrs["synthetic"] = True
    return frame

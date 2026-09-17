import os
from typing import Any, Dict, List

import pandas as pd

from app.database.db import get_db_connection
from app.services.broker_candle_feed import get_broker_multi_timeframe_candles


_TIMEFRAME_MAP = {
    "5m": "M5",
    "15m": "M15",
    "1h": "H1",
    "4h": "H4",
    "1d": "D1",
}


class HistoricalDataService:
    """Broker-only historical candles. Synthetic market generation is prohibited."""

    @staticmethod
    def get_historical_candles(
        symbol: str = "XAUUSD",
        timeframe: str = "15m",
        days_back: int = 30,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        tf = timeframe.lower()
        broker_tf = _TIMEFRAME_MAP.get(tf)
        if broker_tf is None:
            raise RuntimeError(f"UNSUPPORTED_BROKER_TIMEFRAME:{timeframe}")

        tf_minutes = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}[tf]
        required_bars = max(30, int(days_back * 24 * 60 / tf_minutes))
        if os.getenv("TESTING") == "1":
            from tests.broker_history_fixture import build_broker_history_fixture
            return build_broker_history_fixture(symbol.upper(), tf, required_bars)
        if required_bars > 500:
            raise RuntimeError(
                f"BROKER_HISTORY_INSUFFICIENT:requested={required_bars}:maximum=500"
            )

        all_frames = get_broker_multi_timeframe_candles(symbol.upper(), count=required_bars)
        bars = all_frames.get(broker_tf) or []
        if len(bars) < required_bars:
            raise RuntimeError(
                f"BROKER_HISTORY_INSUFFICIENT:{broker_tf}:{len(bars)}/{required_bars}"
            )

        records = []
        index = []
        for bar in bars[-required_bars:]:
            index.append(pd.to_datetime(float(bar["timestamp"]), unit="s", utc=True))
            records.append({
                "Open": float(bar["open"]),
                "High": float(bar["high"]),
                "Low": float(bar["low"]),
                "Close": float(bar["close"]),
                "Volume": float(bar["volume"]),
            })

        frame = pd.DataFrame(records, index=index).sort_index()
        frame.attrs["data_source"] = "CTRADER_CBOT"
        frame.attrs["synthetic"] = False
        return frame

    def get_candles(
        self,
        symbol: str = "XAUUSD",
        timeframe: str = "15m",
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        frame = self.get_historical_candles(
            symbol=symbol,
            timeframe=timeframe,
            days_back=days,
        )
        return [
            {
                "symbol": symbol.upper(),
                "timeframe": timeframe,
                "timestamp": idx.isoformat(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]),
                "source": "CTRADER_CBOT",
            }
            for idx, row in frame.iterrows()
        ]

    @staticmethod
    def save_candles_to_db(symbol: str, timeframe: str, df: pd.DataFrame):
        if df.attrs.get("synthetic") is not False or df.attrs.get("data_source") != "CTRADER_CBOT":
            raise RuntimeError("UNVERIFIED_CANDLE_PERSISTENCE_BLOCKED")
        with get_db_connection() as conn:
            records = []
            for idx, row in df.iterrows():
                timestamp = idx.isoformat() if hasattr(idx, "isoformat") else str(idx)
                records.append((
                    symbol.upper(), timeframe, timestamp,
                    float(row["Open"]), float(row["High"]), float(row["Low"]),
                    float(row["Close"]), float(row["Volume"]),
                ))
            conn.executemany(
                """
                INSERT OR REPLACE INTO candles
                (symbol, timeframe, timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )
            conn.commit()


historical_data_service = HistoricalDataService()

import pytest
from app.services import broker_candle_feed as feed


def _bars(count=60):
    return [
        {"timestamp": i, "open": 100+i, "high": 101+i, "low": 99+i, "close": 100.5+i, "volume": 1}
        for i in range(1, count + 1)
    ]


def test_broker_mtf_has_required_timeframes(monkeypatch):
    def fake_get(path, timeout=12.0):
        if path == "/":
            return {"account_id": "5908018", "is_live": False}
        assert path.startswith("/candles?")
        return _bars(60)
    monkeypatch.setattr(feed, "_get_json", fake_get)
    result = feed.get_broker_multi_timeframe_candles("XAUUSD", 60)
    assert set(result) == {"M5", "M15", "H1", "H4", "D1"}
    assert all(len(result[tf]) == 60 for tf in result)
    assert all(result[tf][0]["timestamp"] < result[tf][-1]["timestamp"] for tf in result)


def test_broker_mtf_fails_closed_on_wrong_account(monkeypatch):
    monkeypatch.setattr(feed, "_get_json", lambda path, timeout=12.0: {"account_id": "999", "is_live": False})
    with pytest.raises(RuntimeError, match="ACCOUNT_MISMATCH"):
        feed.get_broker_multi_timeframe_candles("XAUUSD", 60)


def test_broker_mtf_fails_closed_on_live_account(monkeypatch):
    monkeypatch.setattr(feed, "_get_json", lambda path, timeout=12.0: {"account_id": "5908018", "is_live": True})
    with pytest.raises(RuntimeError, match="LIVE_ACCOUNT_BLOCKED"):
        feed.get_broker_multi_timeframe_candles("XAUUSD", 60)


def test_broker_mtf_rejects_non_array_candles(monkeypatch):
    def fake_get(path, timeout=12.0):
        return {"account_id": "5908018", "is_live": False} if path == "/" else {"status": "ONLINE"}
    monkeypatch.setattr(feed, "_get_json", fake_get)
    with pytest.raises(RuntimeError, match="INVALID_RESPONSE"):
        feed.get_broker_multi_timeframe_candles("XAUUSD", 60)

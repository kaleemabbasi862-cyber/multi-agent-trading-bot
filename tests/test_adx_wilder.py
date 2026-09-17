from app.engine.technical_indicators import technical_indicators


def _candles(prices):
    return [
        {"high": p + 1.0, "low": p - 1.0, "close": p}
        for p in prices
    ]


def test_adx_requires_enough_history():
    result = technical_indicators.calculate_adx(_candles(range(20)), 14)
    assert result["adx"] == 0.0
    assert result["trend_strength"] == "INSUFFICIENT_DATA"


def test_adx_detects_persistent_uptrend():
    result = technical_indicators.calculate_adx(_candles(range(100, 140)), 14)
    assert result["adx"] >= 40.0
    assert result["plus_di"] > result["minus_di"]
    assert result["trend_strength"] == "VERY_STRONG"


def test_adx_detects_persistent_downtrend():
    result = technical_indicators.calculate_adx(_candles(range(140, 100, -1)), 14)
    assert result["adx"] >= 40.0
    assert result["minus_di"] > result["plus_di"]
    assert result["trend_strength"] == "VERY_STRONG"


def test_adx_stays_bounded():
    prices = [100, 101, 99, 102, 98, 103, 97, 104, 98, 103] * 4
    result = technical_indicators.calculate_adx(_candles(prices), 14)
    assert 0.0 <= result["adx"] <= 100.0
    assert 0.0 <= result["plus_di"] <= 100.0
    assert 0.0 <= result["minus_di"] <= 100.0

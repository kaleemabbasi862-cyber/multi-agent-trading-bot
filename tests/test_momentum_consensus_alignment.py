import time
from app.database.models import SignalPayload
from app.agents.technical_agent import technical_agent
from app.agents.liquidity_agent import liquidity_agent

def _signal(action):
    return SignalPayload(symbol="XAUUSD", action=action, entry_price=4375.0,
        stop_loss=4381.0 if action == "SELL" else 4369.0,
        take_profit=4363.0 if action == "SELL" else 4387.0, timeframe="15m")

def _market(action="SELL", aligned=True):
    trend = "BEARISH" if action == "SELL" else "BULLISH"
    structure = f"{trend}_TREND"
    event = f"{trend}_CHOCH"
    return {
        "source": "CTRADER_CBOT", "candle_source": "CTRADER_CBOT",
        "updated_at": time.time(), "price": 4375.0, "spread": 0.13,
        "high_24h": 4399.0, "low_24h": 4373.0,
        "indicators": {"rsi": 38.0, "ema_20": 4381.0, "ema_50": 4372.0,
            "ema_200": 4355.0, "ema_20_1h": 4365.0, "ema_50_1h": 4342.0,
            "trend_1h": "BULLISH", "support": 4373.0, "resistance": 4399.0},
        "_pretrade": {"setup": {"direction": action}, "mtf": {
            "intraday_trend": trend, "intraday_aligned": aligned,
            "timeframe_breakdown": {"M5": {"trend": trend}, "M15": {"trend": trend}}},
            "smc": {"structure": structure, "latest_event": event,
                "dealing_range": {"range_high": 4399.0, "range_low": 4334.0,
                    "equilibrium": 4366.5,
                    "zone": "PREMIUM" if action == "SELL" else "DISCOUNT"}}}}

def test_confirmed_intraday_sell_survives_opposing_h1_context():
    decision = technical_agent.evaluate(_signal("SELL"), _market("SELL"))
    assert decision.direction == "SELL"
    assert decision.decision == "PASS"
    assert decision.score >= 65.0
    assert "M5/M15 momentum aligned BEARISH" in decision.reasoning_summary

def test_unconfirmed_intraday_sell_keeps_countertrend_penalty():
    decision = technical_agent.evaluate(_signal("SELL"), _market("SELL", aligned=False))
    assert decision.decision == "FAIL"
    assert decision.score < 45.0

def test_liquidity_uses_scanner_dealing_range():
    decision = liquidity_agent.evaluate(_signal("SELL"), _market("SELL"))
    assert decision.metrics["dealing_zone"] == "PREMIUM"
    assert decision.metrics["is_premium"] is True
    assert decision.score >= 90.0

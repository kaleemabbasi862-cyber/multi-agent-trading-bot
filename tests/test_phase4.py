import unittest
import datetime
from app.database.db import db
from app.services.economic_calendar import (
    EconomicCalendarService,
    PRE_EVENT_LOCKOUT_MINUTES,
    POST_EVENT_COOLDOWN_MINUTES
)
from app.services.news_engine import NewsEngine
from app.agents.guardian import guardian
from app.database.models import SignalPayload
from fastapi.testclient import TestClient
from main_native import app

calendar_svc = EconomicCalendarService()
news_svc = NewsEngine()
client = TestClient(app)

def test_economic_calendar_and_lockout_windows():
    """Validates economic event seeding, pre-event blackout, and post-event cooldown."""
    try:
        base_time = datetime.datetime.now(datetime.timezone.utc)
        seeded_ids = calendar_svc.seed_mock_schedule(base_date=base_time)
        assert len(seeded_ids) > 0, "Failed to seed calendar"

        events = db.get_economic_events(limit=10, include_mock=True)
        assert len(events) > 0, "No events returned from SQLite"

        # Pre-event lockout test: event in 10 mins (within 30m EXTREME window)
        pre_event_time = base_time + datetime.timedelta(minutes=10)
        db.save_economic_event({
            "id": "EVT_TEST_FOMC_PRE_AUTO",
            "timestamp": pre_event_time.isoformat(),
            "currency": "USD",
            "country": "US",
            "event_name": "FOMC Interest Rate Decision",
            "impact": "EXTREME",
            "affected_symbols": ["XAUUSD"]
        })
        lockout_pre = calendar_svc.check_lockout_status(symbol="XAUUSD", now=base_time, include_mock=True)
        assert lockout_pre["is_locked_out"] is True, "Pre-event blackout not triggered"
        assert lockout_pre["lockout_type"] == "PRE_EVENT_BLACKOUT", "Wrong lockout type"

        # Post-event cooldown test: event 5 mins ago (within 15m cooldown)
        post_event_time = base_time - datetime.timedelta(minutes=5)
        db.save_economic_event({
            "id": "EVT_TEST_CPI_POST_AUTO",
            "timestamp": post_event_time.isoformat(),
            "currency": "USD",
            "country": "US",
            "event_name": "US Consumer Price Index (CPI)",
            "impact": "EXTREME",
            "affected_symbols": ["XAUUSD"]
        })
        lockout_post = calendar_svc.check_lockout_status(symbol="XAUUSD", now=base_time, include_mock=True)
        assert lockout_post["is_locked_out"] is True, "Post-event cooldown not triggered"
    finally:
        with db.get_connection() as conn:
            conn.execute("DELETE FROM economic_events WHERE id LIKE 'TEST%' OR id LIKE 'EVT_TEST%'")
            conn.commit()

def test_spread_normalization_guard():
    """Validates post-event spread guard keeping lockout active until spread normalizes."""
    try:
        # Use isolated future date so other test events do not overlap
        eval_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=10)
        # Event happened 25 minutes ago relative to eval_time (cooldown expired, but inside 45m post-news window)
        event_time = eval_time - datetime.timedelta(minutes=25)
        db.save_economic_event({
            "id": "EVT_TEST_NFP_SPREAD_AUTO",
            "timestamp": event_time.isoformat(),
            "currency": "USD",
            "country": "US",
            "event_name": "US Non-Farm Payrolls",
            "impact": "EXTREME",
            "affected_symbols": ["XAUUSD"]
        })

        # Blown out spread ($0.80 on Gold vs $0.35 baseline)
        elevated_res = calendar_svc.check_lockout_status(symbol="XAUUSD", current_spread=0.80, now=eval_time, include_mock=True)
        assert elevated_res["is_locked_out"] is True, "Spread guard should lockout when spread is elevated"
        assert elevated_res["lockout_type"] == "POST_EVENT_SPREAD_GUARD", f"Expected POST_EVENT_SPREAD_GUARD, got {elevated_res['lockout_type']}"

        # Normal spread ($0.32 on Gold)
        normal_res = calendar_svc.check_lockout_status(symbol="XAUUSD", current_spread=0.32, now=eval_time, include_mock=True)
        assert normal_res["spread_status"] == "NORMAL", "Spread should be marked normal"
        assert normal_res["is_locked_out"] is False, "Lockout should be cleared with normal spread"
    finally:
        with db.get_connection() as conn:
            conn.execute("DELETE FROM economic_events WHERE id LIKE 'TEST%' OR id LIKE 'EVT_TEST%'")
            conn.commit()


def test_financial_nlp_news_sentiment_engine():
    """Validates financial sentiment keyword polarity, classification, and Gold/USD implications."""
    # Bullish headline
    bull_res = news_svc.analyze_sentiment("Fed announces emergency rate cut as cooling inflation boosts safe haven gold demand")
    assert bull_res["sentiment"] in ("BULLISH", "STRONG_BULLISH"), f"Expected Bullish, got {bull_res['sentiment']}"
    assert bull_res["gold_implication"] == "BULLISH_GOLD", "Expected Bullish Gold"
    assert bull_res["sentiment_score"] > 0.3, "Sentiment score should be positive"

    # Bearish headline
    bear_res = news_svc.analyze_sentiment("Hot CPI surges trigger aggressive hawkish rate hike fears sending dollar soaring and gold plunging")
    assert bear_res["sentiment"] in ("BEARISH", "STRONG_BEARISH"), f"Expected Bearish, got {bear_res['sentiment']}"
    assert bear_res["gold_implication"] == "BEARISH_GOLD", "Expected Bearish Gold"
    assert bear_res["sentiment_score"] < -0.3, "Sentiment score should be negative"

    # Ingestion into SQLite
    ingested = news_svc.ingest_news("Central banks accelerate gold buying amid sovereign bond yield drop", source="TEST")
    assert ingested["id"] is not None
    recent = db.get_recent_news(limit=5)
    assert any(n["id"] == ingested["id"] for n in recent), "Ingested headline not found in DB"

def test_phase4_api_endpoints():
    """Validates FastAPI endpoints for economic calendar and news services."""
    res1 = client.get("/api/calendar/events?limit=5")
    assert res1.status_code == 200 and res1.json()["status"] == "SUCCESS"

    res2 = client.get("/api/calendar/lockout-status?symbol=XAUUSD")
    assert res2.status_code == 200 and "is_locked_out" in res2.json()["data"]

    res3 = client.post("/api/news/analyze", json={"headline": "Dovish Fed remarks boost precious metals rally"})
    assert res3.status_code == 200 and res3.json()["status"] == "SUCCESS"

    res4 = client.get("/api/news/sentiment-summary?symbol=XAUUSD")
    assert res4.status_code == 200 and "gold_bias" in res4.json()["data"]


class TestPhase4EconomicNews(unittest.TestCase):
    def tearDown(self):
        with db.get_connection() as conn:
            conn.execute("DELETE FROM economic_events WHERE id LIKE 'TEST%' OR id LIKE 'EVT_TEST%'")

    @classmethod
    def tearDownClass(cls):
        with db.get_connection() as conn:
            conn.execute("DELETE FROM economic_events WHERE id LIKE 'TEST%' OR id LIKE 'EVT_TEST%'")

    def test_01_calendar(self):
        test_economic_calendar_and_lockout_windows()

    def test_02_spread_guard(self):
        test_spread_normalization_guard()

    def test_03_nlp_sentiment(self):
        test_financial_nlp_news_sentiment_engine()

    def test_04_api_endpoints(self):
        test_phase4_api_endpoints()


if __name__ == "__main__":
    unittest.main()

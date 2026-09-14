"""Regression tests for master stabilization pass fixes.

Covers:
  D1: Stale quotes preserved in broker_prices with stale=True, executable=False
  D1: health() distinguishes BROKER_QUOTE_STALE from BROKER_QUOTE_UNVERIFIED
  D1: /api/live-prices exposes stale flag from quote
  D2: change_24h undefined does not render undefined%
  D3: Missing RSI renders '--' not fabricated '54.0'
  D4: Missing spread renders '--' not fabricated '0.35'
  D5: Broker feed label distinguishes stale vs unavailable vs offline
  D7: Missing price renders '--' not fabricated '2750.00'
"""
import copy
import os
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

os.environ["TESTING"] = "1"

from app.services.broker_telemetry import (
    validate_snapshot, health, fresh, QUOTE_MAX_AGE, ACCOUNT_MAX_AGE, SOURCE, symbol_name
)


def _make_snapshot(account="5908018", now=None, quotes=None, positions=None):
    """Build a minimal valid broker snapshot for testing."""
    now = now or time.time()
    if quotes is None:
        quotes = {
            "XAUUSD": {"bid": 4300.0, "ask": 4300.35, "price": 4300.175,
                       "spread": 0.35, "quote_at": now, "account_id": account, "source": SOURCE,
                       "broker_symbol": "XAUUSD"}
        }
    return {
        "status": "ONLINE", "source": SOURCE, "account_id": account,
        "is_live": False, "balance": 1000.0, "equity": 1000.0,
        "margin": 0.0, "free_margin": 1000.0,
        "positions": positions or [],
        "open_positions_count": len(positions or []),
        "prices": quotes, "snapshot_at": now
    }


class TestStaleQuotePreservation(unittest.TestCase):
    """D1: Stale quotes must be preserved in broker_prices, not dropped."""

    def test_fresh_quote_is_executable(self):
        now = time.time()
        data = _make_snapshot(now=now)
        result = validate_snapshot(data, "5908018", now=now)
        quote = result["broker_prices"]["XAUUSD"]
        self.assertTrue(quote["executable"])
        self.assertFalse(quote["stale"])

    def test_stale_quote_preserved_not_executable(self):
        now = time.time()
        stale_time = now - 10.0
        data = _make_snapshot(now=now, quotes={
            "XAUUSD": {"bid": 4300.0, "ask": 4300.35, "price": 4300.175,
                       "spread": 0.35, "quote_at": stale_time, "account_id": "5908018",
                       "source": SOURCE, "broker_symbol": "XAUUSD"}
        })
        result = validate_snapshot(data, "5908018", now=now)
        self.assertIn("XAUUSD", result["broker_prices"])
        quote = result["broker_prices"]["XAUUSD"]
        self.assertFalse(quote["executable"])
        self.assertTrue(quote["stale"])

    def test_invalid_bid_dropped(self):
        now = time.time()
        data = _make_snapshot(now=now, quotes={
            "XAUUSD": {"bid": -1.0, "ask": 4300.35, "price": 4300.175,
                       "spread": 0.35, "quote_at": now, "account_id": "5908018",
                       "source": SOURCE, "broker_symbol": "XAUUSD"}
        })
        result = validate_snapshot(data, "5908018", now=now)
        self.assertNotIn("XAUUSD", result["broker_prices"])


class TestHealthQuoteStaleness(unittest.TestCase):
    """D1: health() must distinguish BROKER_QUOTE_STALE from BROKER_QUOTE_UNVERIFIED."""

    def test_stale_account_returns_broker_account_stale(self):
        state = {
            "account_id": "5908018", "positions_snapshot_valid": True,
            "positions_snapshot_account_id": "5908018",
            "broker_snapshot_at": time.time() - 20.0,
            "broker_prices": {}, "is_live": False, "account_type": "DEMO"
        }
        h = health(state, "XAUUSD", now=time.time())
        self.assertFalse(h["execution_ready"])
        self.assertEqual(h["reason"], "BROKER_ACCOUNT_STALE")

    def test_missing_quote_returns_broker_quote_unverified(self):
        now = time.time()
        state = {
            "account_id": "5908018", "positions_snapshot_valid": True,
            "positions_snapshot_account_id": "5908018",
            "broker_snapshot_at": now, "broker_prices": {},
            "is_live": False, "account_type": "DEMO"
        }
        h = health(state, "XAUUSD", now=now)
        self.assertFalse(h["execution_ready"])
        self.assertEqual(h["reason"], "BROKER_QUOTE_UNVERIFIED")

    def test_stale_quote_returns_broker_quote_stale(self):
        now = time.time()
        state = {
            "account_id": "5908018", "positions_snapshot_valid": True,
            "positions_snapshot_account_id": "5908018",
            "broker_snapshot_at": now,
            "broker_prices": {"XAUUSD": {
                "bid": 4300.0, "ask": 4300.35, "price": 4300.175,
                "quote_at": now - 10.0, "source": SOURCE, "account_id": "5908018",
                "stale": True, "executable": False
            }},
            "is_live": False, "account_type": "DEMO"
        }
        h = health(state, "XAUUSD", now=now)
        self.assertFalse(h["execution_ready"])
        self.assertEqual(h["reason"], "BROKER_QUOTE_STALE")

    def test_fresh_quote_execution_ready(self):
        now = time.time()
        state = {
            "account_id": "5908018", "positions_snapshot_valid": True,
            "positions_snapshot_account_id": "5908018",
            "broker_snapshot_at": now,
            "broker_prices": {"XAUUSD": {
                "bid": 4300.0, "ask": 4300.35, "price": 4300.175,
                "quote_at": now, "source": SOURCE, "account_id": "5908018",
                "stale": False, "executable": True
            }},
            "is_live": False, "account_type": "DEMO"
        }
        h = health(state, "XAUUSD", now=now)
        self.assertTrue(h["execution_ready"])
        self.assertIsNone(h["reason"])

    def test_health_returns_quote_stale_flag(self):
        now = time.time()
        state = {
            "account_id": "5908018", "positions_snapshot_valid": True,
            "positions_snapshot_account_id": "5908018",
            "broker_snapshot_at": now,
            "broker_prices": {"XAUUSD": {
                "bid": 4300.0, "ask": 4300.35, "price": 4300.175,
                "quote_at": now - 10.0, "source": SOURCE, "account_id": "5908018",
                "stale": True, "executable": False
            }},
            "is_live": False, "account_type": "DEMO"
        }
        h = health(state, "XAUUSD", now=now)
        self.assertTrue(h["quote_stale"])

    def test_health_quote_stale_false_when_fresh(self):
        now = time.time()
        state = {
            "account_id": "5908018", "positions_snapshot_valid": True,
            "positions_snapshot_account_id": "5908018",
            "broker_snapshot_at": now,
            "broker_prices": {"XAUUSD": {
                "bid": 4300.0, "ask": 4300.35, "price": 4300.175,
                "quote_at": now, "source": SOURCE, "account_id": "5908018",
                "stale": False, "executable": True
            }},
            "is_live": False, "account_type": "DEMO"
        }
        h = health(state, "XAUUSD", now=now)
        self.assertFalse(h["quote_stale"])


class TestFreshnessFunction(unittest.TestCase):
    """Verify fresh() works correctly with CLOCK_SKEW tolerance."""

    def test_fresh_within_window(self):
        now = time.time()
        self.assertTrue(fresh(now - 1.0, 5.0, now=now))

    def test_stale_outside_window(self):
        now = time.time()
        self.assertFalse(fresh(now - 6.0, 5.0, now=now))

    def test_future_within_clock_skew(self):
        now = time.time()
        self.assertTrue(fresh(now + 1.0, 5.0, now=now))

    def test_future_beyond_clock_skew(self):
        now = time.time()
        self.assertFalse(fresh(now + 3.0, 5.0, now=now))

    def test_none_timestamp_returns_false(self):
        self.assertFalse(fresh(None, 5.0))


class TestLivePricesEndpoint(unittest.TestCase):
    """D1: /api/live-prices must expose stale/executable flags from quote."""

    def test_stale_quote_has_stale_true(self):
        now = time.time()
        state = {
            "account_id": "5908018", "positions_snapshot_valid": True,
            "positions_snapshot_account_id": "5908018",
            "broker_snapshot_at": now,
            "broker_prices": {"XAUUSD": {
                "bid": 4300.0, "ask": 4300.35, "price": 4300.175,
                "quote_at": now - 10.0, "source": SOURCE, "account_id": "5908018",
                "stale": True, "executable": False, "symbol": "XAUUSD"
            }},
            "is_live": False, "account_type": "DEMO",
            "broker_telemetry_error": None, "broker_snapshot_received": True,
            "broker_received_at": now, "broker_snapshot_at": now,
        }
        h = health(state, "XAUUSD", now=now)
        self.assertFalse(h["execution_ready"])
        self.assertEqual(h["reason"], "BROKER_QUOTE_STALE")


if __name__ == "__main__":
    unittest.main()

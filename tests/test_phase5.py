import unittest
import datetime
from app.database.db import db
from app.database.models import SignalPayload
from app.engine.consensus_engine import consensus_engine
from app.engine.explainability_engine import explainability_engine
from fastapi.testclient import TestClient
from main_native import app
import ctrader_cloud_gateway
from tests.broker_fixtures import install_state

def setup_function():
    ctrader_cloud_gateway.switch_active_account("5908018")
    install_state(ctrader_cloud_gateway, bid=2349.9, ask=2350.0)

client = TestClient(app)

def test_7_agents_weighted_consensus_approval():
    """Validates full 7-agent consensus pipeline with high-conviction valid setup."""
    now = datetime.datetime.now(datetime.timezone.utc)
    signal = SignalPayload(
        id="SIG_PHASE5_CONSENSUS_PASS",
        symbol="XAUUSD",
        action="BUY",
        entry_price=2350.00,
        stop_loss=2344.00,
        take_profit=2364.00,
        timeframe="15m",
        volume=0.01,
        account_id="5908018"
    )
    
    market_data = {
        "symbol": "XAUUSD",
        "price": 2350.00,
        "spread": 0.25,
        "high_24h": 2368.00,
        "low_24h": 2338.00,
        "updated_at": now.timestamp(),
        "indicators": {
            "rsi": 58.0,
            "ema_20": 2348.0,
            "ema_50": 2345.0,
            "ema_200": 2335.0,
            "ema_20_1h": 2346.0,
            "ema_50_1h": 2342.0,
            "trend_1h": "BULLISH",
            "support": 2342.0,
            "resistance": 2362.0
        }
    }
    
    macro_data = {
        "minutes_to_next_high_impact_news": 180,
        "minutes_since_last_event": 120,
        "next_event_name": "None",
        "usd_sentiment": "BEARISH_USD",
        "gold_macro_bias": "BULLISH_GOLD"
    }
    
    account_status = {
        "balance": 1000.0,
        "equity": 1000.0,
        "open_positions": [],
        "is_connected": True,
        "daily_loss": 0.0,
        "consecutive_losses": 0
    }

    res = consensus_engine.process_signal(
        signal=signal,
        market_data=market_data,
        macro_data=macro_data,
        account_status=account_status,
        save_to_db=True
    )

    assert res.decision_status == "APPROVED", f"Expected APPROVED, got {res.decision_status}"
    assert res.decision_score >= 80.0, f"Expected score >= 80, got {res.decision_score}"
    assert len(res.agent_decisions) == 5, "Expected 5 analytical agent evaluations"
    assert "URDU EXPLANATION" in res.full_analysis, "Urdu explanation must be synthesized"

def test_hard_risk_veto_overrides_consensus():
    """Validates that Risk Agent or Guardian veto immediately blocks trade regardless of other agent scores."""
    now = datetime.datetime.now(datetime.timezone.utc)
    # R:R of 1:1.0 (fails minimum 1:2.0 requirement)
    signal = SignalPayload(
        id="SIG_PHASE5_RISK_VETO",
        symbol="XAUUSD",
        action="BUY",
        entry_price=2350.00,
        stop_loss=2345.00,
        take_profit=2355.00,
        timeframe="15m",
        volume=0.01,
        account_id="5908018"
    )
    
    market_data = {
        "symbol": "XAUUSD",
        "price": 2350.00,
        "spread": 0.25,
        "updated_at": now.timestamp(),
        "indicators": {
            "rsi": 58.0,
            "ema_20": 2348.0,
            "ema_50": 2345.0,
            "ema_200": 2335.0,
            "ema_20_1h": 2346.0,
            "ema_50_1h": 2342.0,
            "trend_1h": "BULLISH",
            "support": 2342.0,
            "resistance": 2362.0
        }
    }
    macro_data = {"minutes_to_next_high_impact_news": 180, "minutes_since_last_event": 120}
    account_status = {"balance": 1000.0, "equity": 1000.0, "open_positions": [], "is_connected": True}

    res = consensus_engine.process_signal(signal, market_data, macro_data, account_status, save_to_db=True)
    assert res.decision_status == "BLOCKED", f"Expected BLOCKED due to Risk Veto, got {res.decision_status}"
    assert not res.risk_check.passed, "Risk check should fail"

def test_decision_dna_persistence_and_retrieval():
    """Validates Decision DNA snapshot generation, SQLite persistence, and API retrieval."""
    now = datetime.datetime.now(datetime.timezone.utc)
    sig_id = f"SIG_DNA_{now.strftime('%Y%m%d%H%M%S')}"
    signal = SignalPayload(
        id=sig_id,
        symbol="XAUUSD",
        action="BUY",
        entry_price=2350.00,
        stop_loss=2344.00,
        take_profit=2364.00,
        timeframe="15m",
        volume=0.01,
        account_id="5908018"
    )
    market_data = {"symbol": "XAUUSD", "price": 2350.00, "spread": 0.25, "updated_at": now.timestamp(), "indicators": {}}
    macro_data = {"minutes_to_next_high_impact_news": 180, "minutes_since_last_event": 120}
    account_status = {"balance": 1000.0, "equity": 1000.0, "open_positions": [], "is_connected": True}

    consensus_engine.process_signal(signal, market_data, macro_data, account_status, save_to_db=True)
    
    # Retrieve directly from DB
    dna = db.get_decision_dna(sig_id)
    assert dna is not None, "Decision DNA must be persisted in SQLite"
    assert dna["signal_id"] == sig_id
    assert "explainability" in dna
    assert "agent_evaluations" in dna

    # Test API endpoint
    api_res = client.get(f"/api/signals/dna/{sig_id}")
    assert api_res.status_code == 200, "API Decision DNA endpoint failed"
    assert api_res.json()["dna"]["signal_id"] == sig_id

def test_bilingual_explainability_synthesis():
    """Validates Urdu and English synthesis produced by ExplainabilityEngine."""
    signal = SignalPayload(
        id="SIG_EXP_TEST",
        symbol="XAUUSD",
        action="BUY",
        entry_price=2350.00,
        stop_loss=2344.00,
        take_profit=2364.00,
        timeframe="15m"
    )
    explanation = explainability_engine.generate_explanation(
        signal=signal,
        status="APPROVED",
        score=88.5,
        agent_decisions=[],
        risk_check=None
    )
    assert "HIGH-CONVICTION" in explanation["headline_en"]
    assert "منظور" in explanation["headline_ur"]
    assert len(explanation["summary_en"]) > 50
    assert len(explanation["summary_ur"]) > 50


class TestPhase5Consensus(unittest.TestCase):
    def test_01_consensus(self):
        from app.engine import consensus_engine as consensus_module
        consensus_module._PROCESSED_SIGNAL_IDS.clear()
        test_7_agents_weighted_consensus_approval()

    def test_02_risk_veto(self):
        test_hard_risk_veto_overrides_consensus()

    def test_03_dna(self):
        test_decision_dna_persistence_and_retrieval()

    def test_04_bilingual(self):
        test_bilingual_explainability_synthesis()


if __name__ == "__main__":
    unittest.main()

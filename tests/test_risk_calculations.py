from app.database.models import SignalPayload
from app.agents.risk_agent import risk_agent

def test_risk_agent_passes_valid_gold_trade():
    sig = SignalPayload(
        symbol="XAUUSD",
        action="BUY",
        entry_price=2750.0,
        stop_loss=2744.0, # $6.00 SL
        take_profit=2762.0 # $12.00 TP (1:2 R:R)
    )
    acc = {"balance": 1000.0, "equity": 1000.0, "free_margin": 1000.0, "open_positions": [], "daily_loss": 0.0}
    market = {"spread": 0.35, "pip_size": 0.01}
    
    dec, risk_check = risk_agent.evaluate(sig, acc, market)
    assert risk_check.passed is True
    assert risk_check.rr_ratio >= 2.0
    assert dec.decision == "PASS"

def test_risk_agent_vetoes_insufficient_rr():
    sig = SignalPayload(
        symbol="XAUUSD",
        action="BUY",
        entry_price=2750.0,
        stop_loss=2744.0, # $6.00 SL
        take_profit=2753.0 # $3.00 TP (1:0.5 R:R < 2.0)
    )
    acc = {"balance": 1000.0, "equity": 1000.0, "free_margin": 1000.0, "open_positions": []}
    market = {"spread": 0.35, "pip_size": 0.01}
    
    dec, risk_check = risk_agent.evaluate(sig, acc, market)
    assert risk_check.passed is False
    assert dec.decision == "VETO"
    assert "Insufficient Risk:Reward" in risk_check.veto_reason

def test_risk_agent_vetoes_circuit_breaker():
    sig = SignalPayload(
        symbol="XAUUSD",
        action="BUY",
        entry_price=2750.0,
        stop_loss=2744.0,
        take_profit=2762.0
    )
    acc = {"balance": 1000.0, "equity": 994.0, "free_margin": 994.0, "open_positions": [], "daily_loss": -6.50}
    market = {"spread": 0.35, "pip_size": 0.01}
    
    dec, risk_check = risk_agent.evaluate(sig, acc, market)
    assert risk_check.passed is False
    assert dec.decision == "VETO"
    assert "Circuit Breaker" in risk_check.veto_reason

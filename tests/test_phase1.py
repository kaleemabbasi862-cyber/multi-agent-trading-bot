import os
import logging
from app.services.credential_store import credential_store, dpapi_encrypt, dpapi_decrypt
from app.services.logger import SecretMaskingFilter, get_recent_logs
from app.database.db import db, get_db_connection
from app.config import settings
from app.agents.guardian import guardian
from app.database.models import SignalPayload

def test_dpapi_credential_store():
    """Test encryption, decryption, retrieval, and masking in CredentialStore."""
    test_secret = "secret_trading_token_xyz_987654321"
    credential_store.set_secret("TEST_SECRET_KEY", test_secret)
    
    # Verify retrieval
    retrieved = credential_store.get_secret("TEST_SECRET_KEY")
    assert retrieved == test_secret, f"Expected {test_secret}, got {retrieved}"
    
    # Verify masking
    masked = credential_store.mask_secret("TEST_SECRET_KEY")
    assert "..." in masked, f"Masked format invalid: {masked}"
    assert "987654321" not in masked[:10], f"Secret was not properly masked: {masked}"
    
    # Direct DPAPI check
    enc = dpapi_encrypt("DirectSecret123")
    dec = dpapi_decrypt(enc)
    assert dec == "DirectSecret123", f"DPAPI decrypt failed: {dec}"

def test_secret_masking_logger():
    """Test that the SecretMaskingFilter masks tokens and passwords."""
    raw_message = "Connecting with client_secret: super_secret_pass_12345678 and token: abcdef123456"
    masked = SecretMaskingFilter.mask_secrets(raw_message)
    assert "super_secret_pass_12345678" not in masked, "Secret was not masked in log message!"
    assert "***MASKED***" in masked, "Mask token missing from log output!"

def test_expanded_database_schema():
    """Test saving and querying trade journal, system logs, and risk events."""
    # Test System Logs
    db.log_system_log(level="INFO", module="UnitTest", message="Test system log message")
    logs = db.get_system_logs(limit=10, level_filter="INFO")
    assert len(logs) > 0, "No system logs returned"
    assert any(l["module"] == "UnitTest" for l in logs), "UnitTest log entry not found"
    
    # Test Risk Events
    db.log_risk_event(event_type="TEST_BREAKER", account_id="5908018", severity="WARNING", details="Test risk trigger")
    revs = db.get_risk_events(limit=10)
    assert len(revs) > 0, "No risk events returned"
    assert any(r["event_type"] == "TEST_BREAKER" for r in revs), "TEST_BREAKER event not found"
    
    # Test Trade Journal
    test_trade_id = "TRD_TEST_9999"
    db.save_trade({
        "id": test_trade_id,
        "symbol": "XAUUSD",
        "direction": "BUY",
        "entry_price": 2750.0,
        "stop_loss": 2744.0,
        "take_profit": 2762.0,
        "volume": 0.01,
        "status": "CLOSED"
    })
    db.save_trade_journal_entry({
        "id": "JRN_TEST_9999",
        "trade_id": test_trade_id,
        "symbol": "XAUUSD",
        "direction": "BUY",
        "strategy_name": "GoldSniper",
        "market_regime": "TRENDING_BULLISH",
        "mfe": 15.0,
        "mae": 2.5,
        "trade_duration_seconds": 3600,
        "notes": "Journal test note"
    })
    journal_entries = db.get_trade_journal_entries(limit=10)
    assert len(journal_entries) > 0, "No trade journal entries found"
    assert any(j["trade_id"] == test_trade_id for j in journal_entries), "Journal entry not found"

def test_emergency_kill_switch_blocks_trade():
    """Test that setting EMERGENCY_KILL_SWITCH_ACTIVE halts all trading."""
    sig = SignalPayload(
        id="SIG_KILL_TEST",
        symbol="XAUUSD",
        action="BUY",
        entry_price=2750.0,
        stop_loss=2744.0,
        take_profit=2762.0,
        volume=0.01
    )
    market_data = {"price": 2750.0, "spread": 0.20, "updated_at": 9999999999}
    macro_data = {"minutes_to_next_high_impact_news": 999, "minutes_since_last_event": 999}
    acc_status = {"open_positions": [], "daily_loss": 0.0, "consecutive_losses": 0, "is_connected": True}
    
    # 1. Without kill switch -> normal evaluation
    settings.EMERGENCY_KILL_SWITCH_ACTIVE = False
    is_blocked, reason = guardian.check_guard_rules(sig, market_data, macro_data, acc_status, set())
    assert not is_blocked, f"Expected trade not blocked, but got: {reason}"
    
    # 2. With kill switch -> Rule 0 blocked
    settings.EMERGENCY_KILL_SWITCH_ACTIVE = True
    is_blocked, reason = guardian.check_guard_rules(sig, market_data, macro_data, acc_status, set())
    assert is_blocked, "Kill switch failed to block signal"
    assert "Rule 0" in reason or "KILL SWITCH" in reason, f"Unexpected reason: {reason}"
    
    # Reset
    settings.EMERGENCY_KILL_SWITCH_ACTIVE = False

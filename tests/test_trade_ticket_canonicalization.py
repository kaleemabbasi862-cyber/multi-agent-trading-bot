import sqlite3
import pytest
from app.database import db as db_module
from app.database.schema import init_db_schema

@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    path = str(tmp_path / "canonical.db")
    monkeypatch.setattr(db_module.settings, "DATABASE_PATH", path)
    with db_module.get_db_connection() as conn:
        init_db_schema(conn)
    return path

def trade(row_id, ticket="T100", account="5908018", env="DEMO", **extra):
    data = dict(id=row_id, symbol="XAUUSD", direction="SELL",
                entry_price=4300.0, stop_loss=4306.0, take_profit=4288.0,
                volume=0.01, ticket_id=ticket, broker_account_id=account,
                execution_environment=env, is_broker_verified=1,
                provenance="BROKER_DEMO_VERIFIED")
    data.update(extra)
    return data

def rows(ticket):
    with db_module.get_db_connection() as conn:
        return conn.execute("SELECT * FROM trades WHERE ticket_id=? ORDER BY rowid", (ticket,)).fetchall()

def test_same_verified_ticket_is_canonical(isolated_db):
    db_module.db.save_trade(trade("CT_T100", signal_id="GW"))
    db_module.db.save_trade(trade("TRD_1", signal_id="ENGINE"))
    result = rows("T100")
    assert len(result) == 1
    assert result[0]["id"] == "CT_T100"
    assert result[0]["signal_id"] == "ENGINE"

def test_reverse_order_is_canonical(isolated_db):
    db_module.db.save_trade(trade("TRD_1"))
    db_module.db.save_trade(trade("CT_T100"))
    assert len(rows("T100")) == 1

def test_same_ticket_different_account_is_separate(isolated_db):
    db_module.db.save_trade(trade("A"))
    db_module.db.save_trade(trade("B", account="OTHER"))
    assert len(rows("T100")) == 2

def test_same_ticket_different_environment_is_separate(isolated_db):
    db_module.db.save_trade(trade("D"))
    db_module.db.save_trade(trade("L", env="LIVE", provenance="BROKER_LIVE_VERIFIED"))
    assert len(rows("T100")) == 2

def test_unverified_rows_are_not_canonicalized(isolated_db):
    first = trade("TEST_A", is_broker_verified=0, provenance="TEST", execution_environment="TEST")
    second = trade("TEST_B", is_broker_verified=0, provenance="TEST", execution_environment="TEST")
    db_module.db.save_trade(first)
    db_module.db.save_trade(second)
    assert len(rows("T100")) == 2

def test_closed_trade_is_not_reopened(isolated_db):
    db_module.db.save_trade(trade("CT_T100", status="CLOSED", exit_price=4290.0,
                                  profit_loss=9.5, closed_at="2026-09-16T10:00:00+00:00"))
    db_module.db.save_trade(trade("TRD_LATE", status="OPEN"))
    result = rows("T100")
    assert len(result) == 1
    assert result[0]["status"] == "CLOSED"
    assert result[0]["exit_price"] == 4290.0
    assert result[0]["profit_loss"] == 9.5

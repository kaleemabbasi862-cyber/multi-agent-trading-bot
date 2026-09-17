import copy
import os
import tempfile

import pytest

_OWNED_RUNTIME = None
if os.environ.get("TESTING") != "1":
    os.environ["TESTING"] = "1"
if not os.environ.get("DATABASE_PATH"):
    _OWNED_RUNTIME = tempfile.TemporaryDirectory(prefix="tradetalk_pytest_", ignore_cleanup_errors=True)
    db_fd, db_path = tempfile.mkstemp(dir=_OWNED_RUNTIME.name, suffix=".db")
    os.close(db_fd)
    os.environ["DATABASE_PATH"] = db_path

import ctrader_cloud_gateway as gateway
from app.config import settings


@pytest.fixture(autouse=True)
def isolate_gateway_state():
    state = copy.deepcopy(gateway.GATEWAY_STATE)
    accounts = copy.deepcopy(gateway.LINKED_ACCOUNTS)
    close_ts = gateway.LAST_TRADE_CLOSE_TIMESTAMP
    kill_switch = getattr(settings, "EMERGENCY_KILL_SWITCH_ACTIVE", False)
    yield
    gateway.GATEWAY_STATE.clear()
    gateway.GATEWAY_STATE.update(state)
    gateway.LINKED_ACCOUNTS.clear()
    gateway.LINKED_ACCOUNTS.update(accounts)
    gateway.LAST_TRADE_CLOSE_TIMESTAMP = close_ts
    settings.EMERGENCY_KILL_SWITCH_ACTIVE = kill_switch


def pytest_sessionfinish(session, exitstatus):
    if _OWNED_RUNTIME is not None:
        _OWNED_RUNTIME.cleanup()

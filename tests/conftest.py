import copy
import pytest
import ctrader_cloud_gateway as gateway
from app.config import settings

@pytest.fixture(autouse=True)
def isolate_gateway_state():
    state = copy.deepcopy(gateway.GATEWAY_STATE)
    accounts = copy.deepcopy(gateway.LINKED_ACCOUNTS)
    close_ts = gateway.LAST_TRADE_CLOSE_TIMESTAMP
    kill_switch = getattr(settings, "EMERGENCY_KILL_SWITCH_ACTIVE", False)
    testing_env = __import__("os").environ.get("TESTING")
    yield
    gateway.GATEWAY_STATE.clear(); gateway.GATEWAY_STATE.update(state)
    gateway.LINKED_ACCOUNTS.clear(); gateway.LINKED_ACCOUNTS.update(accounts)
    gateway.LAST_TRADE_CLOSE_TIMESTAMP = close_ts
    settings.EMERGENCY_KILL_SWITCH_ACTIVE = kill_switch
    import os
    if testing_env is None: os.environ.pop("TESTING", None)
    else: os.environ["TESTING"] = testing_env

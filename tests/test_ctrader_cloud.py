import ctrader_cloud_gateway
import cbot_bridge
from unittest.mock import patch, Mock
from tests.broker_fixtures import install_state

def test_ctrader_cloud_order_execution():
    # Ensure baseline active account is 5908018
    ctrader_cloud_gateway.switch_active_account("5908018")
    install_state(ctrader_cloud_gateway, bid=2749.90, ask=2750.00)
    
    # 1. Test Gateway Status
    status = ctrader_cloud_gateway.get_gateway_status()
    assert status["is_connected"] is True
    assert status["cloud_server_active"] is True
    assert status["account_id"] == "5908018"

    # Clean any leftover test positions and cooldown
    ctrader_cloud_gateway.reset_cooldown()

    # 2. Test Server-Side Execution of Gold Order (with unit test bridge mock)
    orig_dispatch = ctrader_cloud_gateway.dispatch_local_bridge_order
    orig_price = ctrader_cloud_gateway.get_live_price
    orig_telemetry = ctrader_cloud_gateway.sync_local_cbot_telemetry
    ctrader_cloud_gateway.dispatch_local_bridge_order = lambda *args, **kwargs: {
        "status": "SUCCESS", "position_id": 99999, "entry_price": 2750.00, "symbol": "XAUUSD", "sl": 2744.00, "tp": 2762.00
    }
    ctrader_cloud_gateway.sync_local_cbot_telemetry = lambda *args, **kwargs: ctrader_cloud_gateway.GATEWAY_STATE
    ctrader_cloud_gateway.get_live_price = lambda *args, **kwargs: {"bid": 2749.90, "ask": 2750.00, "price": 2749.95, "spread": 0.10, "source": "CTRADER_CBOT", "executable": True, "stale": False, "quote_at": "2026-09-16T12:00:00+00:00"}

    try:
        res = ctrader_cloud_gateway.execute_market_order(
            symbol="XAUUSD",
            action="BUY",
            lot_size=0.01,
            sl_price=2744.00,
            tp_price=2762.00,
            signal_id="SIG_TEST_CLOUD_001",
            comment="Unit Test Cloud Order"
        )

        assert res["status"] == "SUCCESS"
        assert res["mode"] == "CLOUD_SERVER_OPEN_API"
        assert res["symbol"] == "XAUUSD"
        assert res["action"] == "BUY"
        assert res["lot_size"] == 0.01
        assert "ticket" in res

        # 3. Verify Active Position tracking
        cur_status = ctrader_cloud_gateway.get_gateway_status()
        assert len(cur_status["open_positions"]) == 1
        pos = cur_status["open_positions"][0]
        assert pos["symbol"] == "XAUUSD"
        assert pos["type"] == "BUY"

        # 4. Test Max 1 Open Position Blocker or Cooldown Blocker
        rej_res = ctrader_cloud_gateway.execute_market_order(
            symbol="EURUSD",
            action="BUY",
            lot_size=0.01,
            sl_price=1.0800,
            tp_price=1.0900,
            signal_id="SIG_TEST_CLOUD_002"
        )
        assert rej_res["status"] in ("REJECTED_MAX_OPEN_POSITIONS_REACHED", "REJECTED_COOLDOWN_ACTIVE")

        # 5. Test Live Price Update & PnL calculation
        ctrader_cloud_gateway.update_live_market_prices({
            "XAUUSD": {"symbol": "XAUUSD", "price": 2755.00, "bid": 2755.00, "ask": 2755.35}
        })
        updated_pos = ctrader_cloud_gateway.get_gateway_status()["open_positions"][0]
        # Broker-authoritative state ignores synthetic local price mutation.
        assert updated_pos["current_price"] == 2750.00
        assert updated_pos.get("net_profit", 0) == 0

        # 6. Test broker-confirmed Position Close (Forced for unit test)
        with patch.dict("os.environ", {"TESTING": "0"}),              patch("ctrader_cloud_gateway.requests.post") as mock_post,              patch("ctrader_cloud_gateway.requests.get") as mock_get:
            mock_post.return_value = Mock(status_code=200)
            mock_post.return_value.json.return_value = {"status": "SUCCESS", "position_id": 99999}
            mock_get.return_value = Mock(status_code=200)
            mock_get.return_value.json.return_value = [{
                "id": 99999, "position_id": 99999, "symbol": "XAUUSD",
                "closing_price": 2751.0, "net_profit": 0.75,
            }]
            close_res = ctrader_cloud_gateway.close_position(pos["id"], force=True)
        assert close_res["status"] == "SUCCESS"
        assert len(ctrader_cloud_gateway.get_gateway_status()["open_positions"]) == 0

        # 7. Only broker-discovered accounts may be listed or selected.
        acc_data = ctrader_cloud_gateway.get_all_accounts()
        assert acc_data["status"] == "success"
        acc_ids = [str(a["account_id"]) for a in acc_data["accounts"]]
        assert "5908018" in acc_ids
        switch_res = ctrader_cloud_gateway.switch_active_account("UNVERIFIED_TEST_ACCOUNT")
        assert switch_res["status"] == "REJECTED_UNVERIFIED_ACCOUNT"
        assert ctrader_cloud_gateway.get_gateway_status()["account_id"] == "5908018"
    finally:
        ctrader_cloud_gateway.dispatch_local_bridge_order = orig_dispatch
        ctrader_cloud_gateway.get_live_price = orig_price
        ctrader_cloud_gateway.sync_local_cbot_telemetry = orig_telemetry


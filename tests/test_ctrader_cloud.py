import ctrader_cloud_gateway
import cbot_bridge

def test_ctrader_cloud_order_execution():
    # Ensure baseline active account is 5908018
    ctrader_cloud_gateway.switch_active_account("5908018")
    
    # 1. Test Gateway Status
    status = ctrader_cloud_gateway.get_gateway_status()
    assert status["is_connected"] is True
    assert status["cloud_server_active"] is True
    assert status["account_id"] == "5908018"

    # Clean any leftover test positions
    ctrader_cloud_gateway.GATEWAY_STATE["open_positions"] = []

    # 2. Test Server-Side Execution of Gold Order (with unit test bridge mock)
    orig_dispatch = ctrader_cloud_gateway.dispatch_local_bridge_order
    ctrader_cloud_gateway.dispatch_local_bridge_order = lambda *args, **kwargs: {
        "status": "SUCCESS", "position_id": 99999, "entry_price": 2750.00, "symbol": "XAUUSD"
    }

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
    finally:
        ctrader_cloud_gateway.dispatch_local_bridge_order = orig_dispatch

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
    assert updated_pos["current_price"] == 2755.00
    assert updated_pos["net_profit"] > 0

    # 6. Test Position Close (Forced for unit test)
    close_res = ctrader_cloud_gateway.close_position(pos["id"], force=True)
    assert close_res["status"] == "SUCCESS"
    assert len(ctrader_cloud_gateway.get_gateway_status()["open_positions"]) == 0

    # 7. Test Multi-Account Listing and Switching
    acc_data = ctrader_cloud_gateway.get_all_accounts()
    assert acc_data["status"] == "success"
    accounts = acc_data["accounts"]
    assert len(accounts) >= 3
    acc_ids = [str(a["account_id"]) for a in accounts]
    assert "5908018" in acc_ids
    assert "1005621" in acc_ids
    assert "abu_sarim" in acc_ids

    # Switch to 1005621
    switch_res = ctrader_cloud_gateway.switch_active_account("1005621")
    assert switch_res["status"] == "SUCCESS"
    assert switch_res["active_account_id"] == "1005621"
    assert switch_res["gateway_state"]["balance"] == 21.19
    assert ctrader_cloud_gateway.get_gateway_status()["account_id"] == "1005621"

    # Switch to abu_sarim
    switch_sarim = ctrader_cloud_gateway.switch_active_account("abu_sarim")
    assert switch_sarim["status"] == "SUCCESS"
    assert switch_sarim["active_account_id"] == "abu_sarim"
    assert switch_sarim["gateway_state"]["balance"] == 0.72

    # Switch back to 5908018
    switch_back = ctrader_cloud_gateway.switch_active_account("5908018")
    assert switch_back["status"] == "SUCCESS"
    assert switch_back["active_account_id"] == "5908018"
    assert switch_back["gateway_state"]["balance"] > 1000.0
    assert ctrader_cloud_gateway.get_gateway_status()["account_id"] == "5908018"


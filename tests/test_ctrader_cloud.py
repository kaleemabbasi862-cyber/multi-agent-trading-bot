import ctrader_cloud_gateway
import cbot_bridge

def test_ctrader_cloud_order_execution():
    # 1. Test Gateway Status
    status = ctrader_cloud_gateway.get_gateway_status()
    assert status["is_connected"] is True
    assert status["cloud_server_active"] is True
    assert status["account_id"] == "1005621"

    # Clean any leftover test positions
    ctrader_cloud_gateway.GATEWAY_STATE["open_positions"] = []

    # 2. Test Server-Side Execution of Gold Order
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

    # 4. Test Max 1 Open Position Blocker
    rej_res = ctrader_cloud_gateway.execute_market_order(
        symbol="EURUSD",
        action="BUY",
        lot_size=0.01,
        sl_price=1.0800,
        tp_price=1.0900,
        signal_id="SIG_TEST_CLOUD_002"
    )
    assert rej_res["status"] == "REJECTED_MAX_OPEN_POSITIONS_REACHED"

    # 5. Test Live Price Update & PnL calculation
    ctrader_cloud_gateway.update_live_market_prices({
        "XAUUSD": {"symbol": "XAUUSD", "price": 2755.00, "bid": 2755.00, "ask": 2755.35}
    })
    updated_pos = ctrader_cloud_gateway.get_gateway_status()["open_positions"][0]
    assert updated_pos["current_price"] == 2755.00
    assert updated_pos["net_profit"] > 0

    # 6. Test Position Close
    close_res = ctrader_cloud_gateway.close_position(pos["id"])
    assert close_res["status"] == "SUCCESS"
    assert len(ctrader_cloud_gateway.get_gateway_status()["open_positions"]) == 0

# Broker telemetry authority and runtime verification

Source fix for `fix/broker-authoritative-reconciliation`, 2026-09-11.

## Root causes and changes

The runtime audit reported DEMO account 5908018 at $998.81 balance/equity with zero positions, while TradeTalk retained $1004.85 and position 287480624. The local cBot listener was not running and an old TradeTalk process retained its in-memory state. Those runtime facts require restarting the correct processes; editing source cannot update an already-running old process.

The source also allowed account discovery to overwrite balance/equity, both relay implementations dropped broker prices, a background worker copied external quotes into the execution cache, and entry/history values could become fabricated live prices. All those overwrite/fallback paths are removed from broker telemetry. Analytical market data remains separate.

The shared cBot contract now carries `source=CTRADER_CBOT`, `account_id`, `is_live`, `snapshot_at`, explicit positions and account finances, plus `prices.XAUUSD.bid`, `ask`, `broker_symbol` and `quote_at`. Times are UTC Unix seconds. `snapshot_at` is the account observation time; `quote_at` comes from the actual last tick, not the time a relay downloaded it. A disconnected/backtesting cBot does not return an ONLINE snapshot.

The local poller and both cloud-relay paths use the same validator. They require matching account identity, complete finite account values, consistent position counts and account values. Old/duplicate observations cannot roll back state or renew freshness. A validated empty list clears the ledger/cache for that account and DEMO/LIVE mode. Missing telemetry never means zero positions.

Account observations expire after 10 seconds and broker quotes after 5 seconds, with up to 2 seconds allowed for clock skew. Broker entry prices use ask for BUY and bid for SELL. Strategy entry prices that disagree with the executable quote are vetoed. Entry dispatch, Auto-Trade enabling and autonomous position management fail closed. The cBot also checks account, DEMO status, source-observation ages and current prices before a new entry. Existing position limits, protection geometry, emergency/strategy gates and confirmation requirements remain active.

Position management now uses broker quotes. Failed close/modify responses do not optimistically mutate authoritative state; synthetic partial-close accounting is rejected as unsupported until a broker-confirmed partial-close protocol exists. No simulated balance or margin adjustment is presented as broker telemetry.

The dashboard's `/api/live-prices` path is broker-only. It displays bid/ask and observation timestamps, and hides stale account/position/quote values. Its own clock expires data even if HTTP polling stops. Checked-in settings are Auto-Trade OFF and DEMO.

## Verification

Executed with `TESTING=1`, isolated SQLite databases, mocked broker HTTP and isolated settings:

```text
python -m pytest -p no:cacheprovider tests/test_broker_telemetry.py tests/test_broker_reconciliation.py tests/test_phase6_source_integrity.py tests/test_phase6.py tests/test_phase3_soak.py tests/test_phase2_hardening.py tests/test_broker_provenance_integrity.py -q --disable-warnings
70 passed, 15 subtests passed (85 existing deprecation warnings)

node tests/test_dashboard_telemetry.cjs
Dashboard telemetry: 5 assertions passed

python -m compileall -q app ctrader_cloud_gateway.py cloud_telemetry_relay.py main_native.py copilot_agent.py
Passed

git diff --check
Passed
```

No full unrelated test suite was rerun. No trade was placed and no running broker account was enabled. The cBot was not compiled against the cTrader SDK or run inside cTrader in this workspace; that verification is required below. The cBot timestamp/connection APIs were checked against official [Ticks documentation](https://help.ctrader.com/ctrader-algo/references/MarketData/Ticks/Ticks/) and [IServer documentation](https://help.ctrader.com/ctrader-algo/references/Application/IServer/).

## Files changed

- `TradeTalkBridge.cs`
- `ctrader_cloud_gateway.py`
- `cloud_telemetry_relay.py`
- `main_native.py`
- `copilot_agent.py`
- `app/routers/market.py`
- `app/routers/trading.py`
- `app/services/broker_telemetry.py`
- `app/services/ctrader_execution_service.py`
- `app/services/live_safety_gate.py`
- `app/services/autonomous_trader.py`
- `app/services/position_manager_v3.py`
- `app/services/position_sentinel.py`
- `templates/dashboard.html`
- `user_settings.json`
- `run_tests.py`
- `tests/broker_fixtures.py`
- `tests/test_broker_telemetry.py`
- `tests/test_dashboard_telemetry.cjs`
- `tests/test_broker_reconciliation.py`
- `tests/test_phase6_source_integrity.py`
- `tests/test_phase2_hardening.py`
- `tests/test_phase3_soak.py`
- `docs/BROKER_TELEMETRY_FRESHNESS.md`

## Required local DEMO verification — operator only, no orders

1. Close the old TradeTalk app/server and old relay instances. Confirm the stale process serving port 8000 is gone. Use the newly published source, not an older checkout. Keep `user_settings.json` at `auto_trade_enabled: false`, `trading_mode: DEMO`, `account_id: 5908018`; verify environment overrides also specify DEMO. Do not run the autonomous full-system launcher.
2. In cTrader, select DEMO account **5908018**. Replace the cBot source with this commit's `TradeTalkBridge.cs`, build it, and report any compiler errors. Start this bridge on port **5001**. This cBot responds to telemetry GETs and does not autonomously trade. Do not send any order POSTs.
3. Open `http://127.0.0.1:5001/trade/`. Verify `ONLINE`, `CTRADER_CBOT`, account `5908018`, `is_live:false`, recent `snapshot_at`, correct balance/equity/margin/free margin, and `positions:[]` if cTrader still shows zero. Check `prices.XAUUSD.bid/ask` against cTrader's current quote and ensure `quote_at` advances with market ticks. Compare current values; $998.81 and 4317.37/4317.47 are audit observations, not fixed targets. An old bridge without timestamps must remain blocked.
4. From the updated repository, launch exactly one server using the intended Python environment: `python -m uvicorn main_native:app --host 127.0.0.1 --port 8000`. Do not use the full autonomous launcher or enable Auto-Trade. The server's local worker relays the original snapshot to the configured cloud URL; a separate relay is optional, not required for local verification.
5. Open `http://127.0.0.1:8000/api/cbot/status` and `http://127.0.0.1:8000/api/live-prices`. The account response must match cTrader, report zero positions when flat, and show fresh source timestamps. `telemetry.account_fresh` and `execution_ready` should be true only while matching DEMO account and broker quotes are fresh. The XAUUSD quote must show `source:CTRADER_CBOT`, the same account ID and current bid/ask. A true readiness flag is diagnostic; leave Auto-Trade OFF.
6. Hard-refresh the dashboard at `http://127.0.0.1:8000/`. Verify balance/equity, zero positions, broker bid/ask and source timestamps match the two JSON endpoints and cTrader. There must be no ghost 287480624 or external 4425.90 quote presented as current broker data. If using the cloud dashboard, deploy the same source there and verify its corresponding endpoints; publication to GitHub alone is not a deployment. Relay source timestamps must remain unchanged across transport.
7. Stop only the cBot bridge, leave cTrader and TradeTalk open, and wait at least **11 seconds**. The dashboard must show broker telemetry unavailable/stale, unknown positions rather than a fabricated flat account, and no executable quote. `/api/cbot/status` must report `execution_ready:false`; `/api/live-prices` must report `executable:false` with null prices. Do not test this by placing an order or enabling Auto-Trade.
8. Restart the bridge and verify a new snapshot restores the correct values while Auto-Trade remains OFF. Return the build result and redacted JSON from steps 3, 5 and 7. Keep tokens/credentials out of the report.

Stop at this verification. LIVE trading and order dispatch are not authorized by this checklist.

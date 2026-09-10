# Broker-authoritative reconciliation verification

Branch: `fix/broker-authoritative-reconciliation`

Implemented and tested on Windows, 2026-09-11, starting from `e069a48`.

## Changes

- Validate explicit positions, account identity, account type and finite financial values before accepting a local cBot snapshot. A valid empty list clears stale positions; missing, malformed, offline and failed responses retain last-known state and mark telemetry unavailable.
- Reconcile open database trades for the snapshot's DEMO or LIVE mode and broker account, preserving PAPER and other accounts. Absence closes stale records without inventing realized P&L.
- Replace the execution cache from authoritative snapshots. A subsequent outage cannot resurrect cached positions after a confirmed empty snapshot.
- Initialize closed history before price fallback accesses it. Preserve broker equity and margin when updating prices or receiving partial heartbeats. Other-account heartbeats cannot replace active-account positions.
- Persist settings through atomic replacement, propagate write failures, and default missing auto-trade settings to disabled. The dashboard takes toggle state from the saved backend response; unrelated settings changes no longer write a stale auto-trade value.
- Repair missing `Tuple` and `List` imports that prevented test collection. Isolate runner credentials alongside its temporary database and suppress background calendar/news refresh threads under `TESTING`.

Broker dispatch, DEMO execution restrictions, confirmation checks, max-position limits and SL/TP gates remain in place. No runtime account settings were enabled or changed.

## Actual verification

Python 3.12 in a workspace virtual environment, with repository requirements plus pytest/httpx and API support dependencies.

- Focused regression and safety command: `python -m pytest tests/test_broker_reconciliation.py tests/test_phase6_source_integrity.py tests/test_phase3_soak.py tests/test_broker_provenance_integrity.py tests/test_phase2_hardening.py -q`: **41 passed; 8 subtests passed**.
- Full command: `python -m pytest tests -q`: **132 passed; 6 failed; 8 subtests passed**.
- Repository runner: `python run_tests.py`: **60 groups; 57 passed; 3 failed**.
- Original branch snapshot, with only the two missing typing imports repaired to allow collection: **122 passed; the same 6 tests failed**.

Pytest runs explicitly used `TESTING=1` and separate test database paths. The ten new regressions use mocked broker HTTP, a private SQLite database, isolated settings files and backend function calls. They do not place trades.

## Remaining failures and runtime limits

The six full-suite failures reproduced on the baseline are:

1. `test_ctrader_cloud_order_execution`: `REJECTED_UNVERIFIED_MARKET_DATA` instead of success.
2. `test_position_sentinel_no_premature_reversal_close`: existing `default_p` NameError in market-feed fallback.
3. `test_dpapi_credential_store`: Windows DPAPI encryption failed in this sandbox.
4. `test_05_autonomous_trader_lifecycle_and_setup_pipeline`: `EXECUTION_FAILED` instead of success.
5. `TestPhase5Consensus.test_01_consensus`: `BLOCKED` instead of `APPROVED`.
6. `test_08_position_sentinel_subsecond_spread_regression`: the same market-feed fallback NameError.

The repository runner's three failing groups cover DPAPI and the two market-feed failures. No safety checks were relaxed to make these tests pass. A later test attempt exposed an access violation while background feeds were writing during database cleanup; the test-only refresh guards above were added, and both suites then completed with the results recorded here.

The local Windows cTrader application, cBot bridge, real DEMO account snapshots and end-to-end DEMO execution were **not runtime verified**. This change does not certify operational readiness or authorize real-money trading. Those integration checks and the remaining baseline failures still need resolution before deployment.

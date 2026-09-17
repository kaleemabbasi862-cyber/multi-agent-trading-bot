# TradeTalk AI Post-Structure Soak Report

**Date:** 2026-09-17
**Baseline commit:** `36e9f8f`
**Environment:** cTrader DEMO account `5908018`
**Safety:** Auto-Trade OFF; LIVE mode prohibited; no orders submitted.

## Ten-Minute Runtime Soak

- Duration: 604.28 seconds
- Samples: 60/60 valid
- Bridge failures: 0
- Backend failures: 0
- Execution-not-ready samples: 0
- Stale quote samples (>5s): 0
- Stale account samples (>10s): 0
- Wrong-account or LIVE samples: 0
- Position mismatches or nonzero positions: 0
- Invalid quote source samples: 0
- Maximum quote age: 4.878s
- Maximum account age: 2.289s
- Balance delta: $0.00
- Bridge latency median/max: 17.93ms / 423.27ms
- Backend latency median/max: 16.82ms / 92.74ms
- Result: PASS

## Controlled Fail-Closed Verification

- Broker availability, telemetry, provenance and Phase 6 source-integrity suites
- 57 tests passed
- 7 subtests passed
- Runtime remained healthy after isolated verification

## Final Runtime State

DEMO, Auto-Trade OFF, bridge online, execution ready, telemetry fresh,
XAUUSD source `CTRADER_CBOT`, zero open positions, balance/equity $998.82.

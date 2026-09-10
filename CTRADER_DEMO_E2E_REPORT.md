# TRADETALK — cTRADER DEMO END-TO-END VALIDATION REPORT

**Audit Date:** 2026-09-09  
**Broker / Server:** Spotware cTrader Open API / Local cBot Bridge  
**Demo Account:** Spotware `#5908018` (Balance: \$1018.96)  
**Execution Endpoint:** `http://127.0.0.1:5001/trade/`  
**Status:** **OPERATIONAL & AUDITED**

---

## 1. Broker Authentication & Account Resolution

- **Account Authentication:** Successful against Spotware Open API (`#5908018`).
- **Active Balance / Equity:** \$1018.96 / \$1018.96 (Synced directly from cBot Bridge).
- **Symbol Resolution:**
  - Standard symbol `XAUUSD` resolved to Broker Symbol `XAUUSD` (Digits: 2, Pip Size: 0.01).
  - Contract Size: 100 oz per 1.0 lot. Minimum Volume: 0.01 lots.

---

## 2. Live Tick & Market Data Validation

- **Live Stream:** Authenticated via Local cBot Bridge (`/trade/price/XAUUSD`).
- **Live Spot Quotes:** Bid: \$4405.20, Ask: \$4405.50, Spread: \$0.30 (3.0 pips).
- **Market Data Integrity Monitor:** Verified fresh (< 50ms latency), healthy bounds, and non-inverted book.

---

## 3. Real Broker Deal Ticket Verification

Forensic retrieval from the live broker deal history:

| Deal Ticket | Symbol | Type | Volume | Entry Price | Closing Price | Net PnL | Entry Timestamp (UTC) | Closing Timestamp (UTC) | Duration |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `#287137773` | XAUUSD | BUY | 0.01 | \$4395.87 | \$4407.61 | **+\$11.52** | 2026-09-09 16:09:19 | 2026-09-09 16:43:40 | 34m 21s |
| `#287078085` | XAUUSD | BUY | 0.01 | \$4412.32 | \$4424.51 | **+\$11.97** | 2026-09-09 13:55:49 | 2026-09-09 14:04:03 | 8m 14s |
| `#287064181` | XAUUSD | BUY | 0.01 | \$4417.66 | \$4429.95 | **+\$12.07** | 2026-09-09 13:21:31 | 2026-09-09 13:25:12 | 3m 41s |
| `#287058390` | XAUUSD | BUY | 0.01 | \$4407.20 | \$4419.47 | **+\$12.05** | 2026-09-09 13:03:16 | 2026-09-09 13:21:13 | 17m 57s |
| `#287049189` | XAUUSD | BUY | 0.01 | \$4395.97 | \$4408.24 | **+\$12.05** | 2026-09-09 12:34:07 | 2026-09-09 13:03:06 | 28m 59s |
| `#287156680` | XAUUSD | SELL | 0.01 | \$4408.78 | \$4414.85 | **-\$6.29** | 2026-09-09 16:59:13 | 2026-09-09 17:05:47 | 6m 34s |
| `#287125467` | XAUUSD | BUY | 0.01 | \$4401.55 | \$4395.25 | **-\$6.52** | 2026-09-09 15:40:17 | 2026-09-09 16:08:41 | 28m 24s |
| `#287113600` | XAUUSD | BUY | 0.01 | \$4389.22 | \$4382.99 | **-\$6.45** | 2026-09-09 15:14:26 | 2026-09-09 15:19:05 | 4m 39s |
| `#287109736` | XAUUSD | BUY | 0.01 | \$4390.25 | \$4382.69 | **-\$7.78** | 2026-09-09 15:06:49 | 2026-09-09 15:12:00 | 5m 11s |

---

## 4. Lifecycle Operations Verified Against cTrader Bridge

1. **Market Order Execution:** Dispatches authentic market BUY/SELL with server-side SL and TP.
2. **Modify Stop Loss / Take Profit:** Successfully updates broker ticket SL and TP via `/trade/modify`.
3. **Break-Even Lock:** Shifts broker ticket SL to entry + \$0.50 buffer while retaining original TP.
4. **Trailing Stop:** Successfully advances broker ticket SL monotonically as price expands.
5. **Authoritative Reconciliation:** `reconcile_positions()` synchronizes local SQLite cache directly with active broker open tickets.

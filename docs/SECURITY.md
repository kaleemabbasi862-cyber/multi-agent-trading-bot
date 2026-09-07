# TradeTalk V2 — Security & Compliance Architecture

## Security Layers

1. **Authentication & Secret Management**:
   - Secrets and API tokens are strictly isolated in environment variables.
   - Broker credentials and API tokens are never exposed in frontend templates or client API responses.

2. **Webhook Integrity**:
   - HMAC-SHA256 signature verification via `X-TradeTalk-Signature`.
   - Replay protection with maximum 300-second timestamp drift.

3. **Trading Mode Safety Gates**:
   - Default mode is **`PAPER`** (Simulation).
   - **`LIVE`** execution requires explicit user authorization and active circuit breaker checks.

4. **Audit Logging**:
   - Every mode change, signal arbitration, risk veto, trade execution, and backtest run is immutably recorded in the `audit_logs` SQLite table.

# TradeTalk V2 — cTrader Bridge Architecture (`TradeTalkBridge.cs`)

## Overview
`TradeTalkBridge.cs` is a high-performance C# cBot running directly inside cTrader Automate. It communicates with the TradeTalk V2 cloud engine via low-latency REST endpoints.

---

## 1. Responsibilities
1. **Telemetry Streaming**: Dispatches live bid, ask, account balance, equity, margin, and active open positions every 2 seconds via `POST /api/cbot/stream`.
2. **Order Polling & Execution**: Retrieves approved trades from `/api/cbot/orders` and executes market orders with validated Stop Loss and Take Profit.
3. **Emergency Protection**: Continuously scans open positions. If any trade lacks an attached Stop Loss, immediately triggers `ModifyPosition`. If the broker rejects the modification, executes `ClosePosition` to guarantee zero naked risk.
4. **Dynamic Auto Break-Even**: Automatically updates Stop Loss to `EntryPrice + 1.0 pip` as soon as position profit reaches $+15.0$ pips.
5. **Idempotency & Duplicate Protection**: Tracks executed tickets in a thread-safe `HashSet<string>` to prevent double execution.

---

## 2. Setup in cTrader
1. Open **cTrader Automate**.
2. Select or create robot **`TradeTalkBridge`**.
3. Copy and paste the source from [`TradeTalkBridge.cs`](file:///d:/Users/AL%20RAZZAQ/Desktop/Trade%20Talk/TradeTalkBridge.cs).
4. Press **`Ctrl + B`** to Build.
5. Attach to an **`XAUUSD`** chart and click **Run**.

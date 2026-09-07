# TradeTalk V2 — TradingView Webhook Integration & Security

## Overview
TradingView PineScript alerts and webhooks are ingested through `/webhook/tradingview`. Signals undergo cryptographic authentication, rate-limiting, deduplication, and full 7-agent consensus validation before any order is queued for execution.

---

## 1. Webhook Endpoint
- **URL**: `https://multi-agent-trading-bot.onrender.com/webhook/tradingview`
- **Method**: `POST`
- **Headers**:
  - `Content-Type`: `application/json`
  - `X-TradeTalk-Token`: `<WEBHOOK_SECRET_KEY>`
  - `X-TradeTalk-Signature`: (Optional HMAC-SHA256 signature)
  - `X-TradeTalk-Timestamp`: (Current UTC epoch timestamp)

---

## 2. Pine Script Alert Payload Format
```json
{
  "token": "tradetalk_v2_secret_key_884920",
  "symbol": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "entry_price": {{close}},
  "stop_loss": {{plot("StopLoss")}},
  "take_profit": {{plot("TakeProfit")}},
  "timeframe": "15m",
  "strategy_name": "Gold_Sniper_SMC"
}
```

---

## 3. Webhook Pipeline
$$\text{TradingView Alert} \to \text{HMAC/Token Auth} \to \text{Market Quote Validation} \to \text{7 Agents} \to \text{Guardian Gate} \to \text{Execution State Machine}$$

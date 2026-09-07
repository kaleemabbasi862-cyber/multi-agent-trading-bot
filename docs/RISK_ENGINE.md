# TradeTalk V2 — Risk Engine & Capital Preservation Architecture

## Core Philosophy
**"Trade less, trade better. Capital preservation comes before profit."**

---

## 1. Non-Negotiable Risk Rules

| Rule | Enforcement | Value / Formula |
| :--- | :--- | :--- |
| **Max Open Positions** | Hard Cap | Strictly **1 Active Trade** across entire account |
| **Fixed Lot Size** | Contract Normalization | **0.01 Micro-Lot (1 unit)** on XAUUSD |
| **Minimum Risk:Reward** | Pre-Trade Filter | **1:2.0 Minimum** ($R:R \ge 2.0$) |
| **Daily Circuit Breaker**| Auto-Halt | Total daily net loss reaching **-\$5.00** halts all new trades |
| **Consecutive Loss Gate**| Cooldown / Halt | 2 losses $\to$ 2hr cooldown; 3 losses $\to$ 24hr halt |
| **Broker Stop Distance**| Dynamic Buffer | $\text{SL Distance} \ge 3.0\times \text{Spread}$ and $\ge 40$ pips |
| **Auto Break-Even** | Dynamic Profit Lock | Moves SL to Entry Price (+1 pip buffer) at **+15 pips (+\$1.50)** |
| **Emergency Auto-Close**| Broker SL Rejection | If broker rejects SL attachment, closes position within 1 second |

---

## 2. Monetary Risk Formula
For Gold (XAUUSD), where 1 Lot = 100 units:
$$\text{Monetary Risk (\$) } = |\text{Entry} - \text{SL}| \times (\text{Lot Size} \times 100)$$

For 0.01 lot with a \$6.00 Stop Loss:
$$\text{Risk} = \$6.00 \times (0.01 \times 100) = \$6.00 \times 1.0 = \$0.60 \text{ to } \$6.00$$

If calculated monetary risk exceeds the account safety limit, the Risk Management Agent immediately exercises its **VETO POWER**, blocking execution.

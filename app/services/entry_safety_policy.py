"""Deterministic entry guards that sit above the aggregate quality score."""
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Tuple

def directional_location_block_reason(
    direction: str, smc_data: Dict[str, Any]
) -> Optional[str]:
    """Reject chasing BUYs at the top or SELLs at the bottom of the range."""
    side = str(direction or "").upper()
    dealing_range = (smc_data or {}).get("dealing_range") or {}
    zone = str(dealing_range.get("zone", "EQUILIBRIUM")).upper()
    try:
        location_pct = float(dealing_range.get("location_pct", 50.0))
    except (TypeError, ValueError):
        return "NO_TRADE_LOCATION_INVALID: dealing-range location is unavailable."

    if side == "BUY" and (zone == "EXTREME_PREMIUM" or location_pct > 75.0):
        return (
            "NO_TRADE_LOCATION_CHASE: BUY blocked in extreme premium "
            f"({location_pct:.1f}% of dealing range)."
        )
    if side == "SELL" and (zone == "DEEP_DISCOUNT" or location_pct < 25.0):
        return (
            "NO_TRADE_LOCATION_CHASE: SELL blocked in deep discount "
            f"({location_pct:.1f}% of dealing range)."
        )
    return None

def _closed_epoch(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0

def consecutive_loss_lockout(
    recent_trades: Iterable[Dict[str, Any]],
    now_ts: float,
    required_losses: int = 2,
    cooldown_seconds: int = 3600,
) -> Tuple[bool, int]:
    """Return a bounded lockout based only on canonical broker-verified closes."""
    losses = []
    for trade in recent_trades:
        if str(trade.get("status", "")).upper() != "CLOSED":
            continue
        try:
            pnl = float(trade.get("profit_loss") or 0.0)
        except (TypeError, ValueError):
            break
        if pnl >= 0.0:
            break
        losses.append(trade)
        if len(losses) >= required_losses:
            break

    if len(losses) < required_losses:
        return False, 0
    latest_close = _closed_epoch(losses[0].get("closed_at"))
    if latest_close <= 0.0:
        return True, cooldown_seconds
    remaining = int(max(0.0, cooldown_seconds - (now_ts - latest_close)))
    return remaining > 0, remaining

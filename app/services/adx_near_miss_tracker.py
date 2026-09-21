"""Shadow-only tracking for high-quality setups rejected solely by near-threshold ADX."""
import datetime
import json
import threading
import time
from typing import Any, Dict, List

from app.database.db import db
from app.services.entry_safety_policy import directional_location_block_reason

_lock = threading.Lock()


def _utc_iso(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc).isoformat()


def _risk_distance(symbol: str) -> float:
    sym = str(symbol or "").upper()
    if "XAU" in sym or "GOLD" in sym:
        return 6.0
    if "XAG" in sym or "SILVER" in sym:
        return 0.35
    if "JPY" in sym:
        return 0.40
    return 0.0035


class AdxNearMissTracker:
    """Records counterfactual outcomes without creating signals or orders."""

    min_adx = 18.0
    max_adx = 20.0
    observation_seconds = 4 * 60 * 60

    def observe_scan(
        self, scan: Dict[str, Any], entry_price: float, symbol: str, now_ts: float = 0.0
    ) -> bool:
        now_ts = float(now_ts or time.time())
        reason = str(scan.get("decision_reason") or "")
        setup = scan.get("setup") or {}
        quality = scan.get("quality_score") or {}
        adx_info = (scan.get("indicators") or {}).get("adx") or {}
        adx = float(adx_info.get("adx", 0.0)) if isinstance(adx_info, dict) else float(adx_info)
        direction = str(setup.get("direction") or "").upper()
        smc = scan.get("smc") or {}
        structure = str(smc.get("structure") or "RANGE").upper()
        setup_type = str(setup.get("setup_type") or "NO_VALID_SETUP").upper()
        consolidation = (
            structure in ("RANGE", "CONSOLIDATION", "CONSOLIDATING")
            and setup_type != "STRUCTURE_REVERSAL"
        ) or setup_type == "NO_VALID_SETUP"
        location_blocked = directional_location_block_reason(direction, smc) is not None
        spread = float(scan.get("spread_pips") or 0.0)
        spread_blocked = (
            ("XAU" in str(symbol).upper() and spread > 5.0)
            or ("EUR" in str(symbol).upper() and spread > 2.0)
        )
        if (
            not reason.startswith("NO_TRADE_REGIME_ADX")
            or not self.min_adx <= adx < self.max_adx
            or not bool(quality.get("passed"))
            or direction not in ("BUY", "SELL")
            or not bool(setup.get("is_actionable"))
            or consolidation
            or location_blocked
            or bool(scan.get("news_blackout"))
            or spread_blocked
        ):
            return False

        risk = _risk_distance(symbol)
        bucket = int(now_ts // 900)
        opportunity_id = f"ADXNM_{str(symbol).upper()}_{direction}_{bucket}"
        entry = float(entry_price)
        stop = entry - risk if direction == "BUY" else entry + risk
        target_1r = entry + risk if direction == "BUY" else entry - risk
        target_2r = entry + (2.0 * risk) if direction == "BUY" else entry - (2.0 * risk)

        payload = json.dumps({
            "regime": setup.get("regime"),
            "structure": (scan.get("smc") or {}).get("structure"),
            "zone": ((scan.get("smc") or {}).get("dealing_range") or {}).get("zone"),
            "reason": reason,
        }, ensure_ascii=False)
        with _lock, db.get_connection() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO adx_near_miss_opportunities
                (id, symbol, direction, setup_type, detected_at, entry_price, adx,
                 plus_di, minus_di, quality_score, quality_threshold, initial_r,
                 stop_1r, target_1r, target_2r, status, result, max_favorable_r,
                 max_adverse_r, last_price, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN',
                        'PENDING', 0.0, 0.0, ?, ?)""",
                (
                    opportunity_id, str(symbol).upper(), direction,
                    str(setup.get("setup_type") or "UNKNOWN"), _utc_iso(now_ts),
                    entry, adx, float(adx_info.get("plus_di", 0.0)),
                    float(adx_info.get("minus_di", 0.0)),
                    float(quality.get("score", 0.0)),
                    float(quality.get("threshold", 75.0)), risk, stop,
                    target_1r, target_2r, entry, payload,
                ),
            )
            conn.commit()
            return cur.rowcount == 1

    def update_open(self, symbol: str, current_price: float, now_ts: float = 0.0) -> int:
        now_ts = float(now_ts or time.time())
        price = float(current_price)
        updated = 0
        with _lock, db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM adx_near_miss_opportunities WHERE symbol = ? AND status = 'OPEN'",
                (str(symbol).upper(),),
            ).fetchall()
            for raw in rows:
                row = dict(raw)
                sign = 1.0 if row["direction"] == "BUY" else -1.0
                r_move = sign * (price - float(row["entry_price"])) / float(row["initial_r"])
                max_fav = max(float(row["max_favorable_r"]), r_move)
                max_adv = min(float(row["max_adverse_r"]), r_move)
                hit_1r_at = row["hit_1r_at"]
                if max_fav >= 1.0 and not hit_1r_at:
                    hit_1r_at = _utc_iso(now_ts)

                age = now_ts - datetime.datetime.fromisoformat(
                    str(row["detected_at"]).replace("Z", "+00:00")
                ).timestamp()
                status, result, resolved_at = "OPEN", "PENDING", None
                if max_fav >= 2.0:
                    status, result, resolved_at = "RESOLVED", "TARGET_2R", _utc_iso(now_ts)
                elif max_adv <= -1.0:
                    result = "HIT_1R_THEN_STOP" if hit_1r_at else "STOP_1R"
                    status, resolved_at = "RESOLVED", _utc_iso(now_ts)
                elif age >= self.observation_seconds:
                    result = "HIT_1R_ONLY" if hit_1r_at else "EXPIRED_NO_TRIGGER"
                    status, resolved_at = "EXPIRED", _utc_iso(now_ts)

                conn.execute(
                    """UPDATE adx_near_miss_opportunities
                    SET max_favorable_r = ?, max_adverse_r = ?, last_price = ?,
                        last_observed_at = ?, hit_1r_at = ?, status = ?,
                        result = ?, resolved_at = ?
                    WHERE id = ?""",
                    (
                        max_fav, max_adv, price, _utc_iso(now_ts), hit_1r_at,
                        status, result, resolved_at, row["id"],
                    ),
                )
                updated += 1
            conn.commit()
        return updated

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        bounded = max(1, min(int(limit), 500))
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM adx_near_miss_opportunities ORDER BY detected_at DESC LIMIT ?",
                (bounded,),
            ).fetchall()
            return [dict(row) for row in rows]


adx_near_miss_tracker = AdxNearMissTracker()

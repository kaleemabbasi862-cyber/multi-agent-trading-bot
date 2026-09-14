from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from app.database.db import db, get_db_connection
from app.engine.performance import performance_engine
from app.engine.execution_engine import execution_engine
from app.config import settings
from app.services.logger import get_recent_logs
from app.services.credential_store import credential_store
import cbot_bridge
import ctrader_cloud_gateway

router = APIRouter(prefix="/api", tags=["System"])

class KillSwitchRequest(BaseModel):
    active: bool
    reason: Optional[str] = "Manual Operator Emergency Kill Switch"

class UpdateKeyRequest(BaseModel):
    key: str
    value: str

class JournalEntryRequest(BaseModel):
    trade_id: str
    symbol: str
    direction: str
    strategy_name: Optional[str] = "Autonomous_V2"
    market_regime: Optional[str] = "TRENDING"
    mfe: Optional[float] = 0.0
    mae: Optional[float] = 0.0
    trade_duration_seconds: Optional[int] = 0
    news_context: Optional[str] = ""
    ai_reasoning: Optional[str] = ""
    notes: Optional[str] = ""

@router.get("/system-state")
@router.get("/system/health")
async def get_system_health():
    cbot_stat = cbot_bridge.get_cbot_status()
    acc_id = ctrader_cloud_gateway.get_active_account_id()
    perf_stat = db.get_performance_stats(broker_account_id=acc_id) if acc_id else {"closed_trades": 0, "win_rate": 0.0, "net_pnl": 0.0, "gross_profit": 0.0, "gross_loss": 0.0, "profit_factor": 1.0, "avg_trade_pnl": 0.0}
    gw_stat = ctrader_cloud_gateway.get_gateway_status()
    
    return {
        "status": "HEALTHY",
        "version": settings.VERSION,
        "trading_mode": execution_engine.mode,
        "is_live": execution_engine.mode == "LIVE",
        "emergency_kill_switch": settings.EMERGENCY_KILL_SWITCH_ACTIVE,
        "cbot_connected": cbot_stat.get("is_connected", True),
        "ctrader_connected": gw_stat.get("is_connected", True),
        "circuit_breaker_active": cbot_stat.get("circuit_breaker_active", False),
        "database": "SQLITE_WAL_ACTIVE",
        "stats": perf_stat
    }

@router.get("/system/logs")
@router.get("/logs")
async def get_logs_endpoint(limit: int = 100, level: Optional[str] = None):
    """Returns recent structured logs with automatic secret redaction."""
    return get_recent_logs(limit=limit, level_filter=level)

@router.post("/system/kill-switch")
@router.post("/kill-switch")
async def toggle_kill_switch(req: KillSwitchRequest):
    """
    EMERGENCY KILL SWITCH:
    Immediately halts opening of all new trades across Paper, Demo, and Live modes.
    """
    settings.EMERGENCY_KILL_SWITCH_ACTIVE = req.active
    db.log_audit(
        event_type="EMERGENCY_KILL_SWITCH",
        actor="OperatorUI",
        details=f"Kill switch set to {req.active}. Reason: {req.reason}"
    )
    db.log_risk_event(
        event_type="EMERGENCY_KILL_SWITCH",
        account_id=str(settings.CTRADER_ACCOUNT_ID),
        severity="CRITICAL" if req.active else "INFO",
        details=f"Emergency Kill Switch {'ACTIVATED' if req.active else 'DEACTIVATED'}: {req.reason}"
    )
    return {
        "status": "SUCCESS",
        "kill_switch_active": settings.EMERGENCY_KILL_SWITCH_ACTIVE,
        "message": "EMERGENCY KILL SWITCH ENGAGED — ALL NEW TRADING HALTED" if req.active else "Kill switch disengaged. Normal trading allowed."
    }

@router.get("/system/kill-switch/status")
async def get_kill_switch_status():
    return {
        "kill_switch_active": settings.EMERGENCY_KILL_SWITCH_ACTIVE
    }

@router.get("/performance")
async def get_performance_analytics():
    return performance_engine.get_comprehensive_analytics()

@router.get("/system/audit-logs")
async def get_audit_logs():
    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT 50").fetchall()
        return [dict(r) for r in rows]

@router.get("/journal")
@router.get("/trade-journal")
async def get_trade_journal(limit: int = 50):
    return db.get_trade_journal_entries(limit=limit)

@router.post("/journal/entry")
async def create_trade_journal_entry(req: JournalEntryRequest):
    entry_id = f"JRN_{req.trade_id}"
    db.save_trade_journal_entry({
        "id": entry_id,
        "trade_id": req.trade_id,
        "symbol": req.symbol,
        "direction": req.direction,
        "strategy_name": req.strategy_name,
        "market_regime": req.market_regime,
        "mfe": req.mfe,
        "mae": req.mae,
        "trade_duration_seconds": req.trade_duration_seconds,
        "news_context": req.news_context,
        "ai_reasoning": req.ai_reasoning,
        "notes": req.notes
    })
    return {"status": "SUCCESS", "id": entry_id}

@router.get("/risk/events")
async def get_risk_events_endpoint(limit: int = 50):
    return db.get_risk_events(limit=limit)

@router.get("/security/masked-keys")
async def get_masked_security_keys():
    """Returns safe masked representations of credentials for UI display."""
    return {
        "CTRADER_CLIENT_ID": credential_store.mask_secret("CTRADER_CLIENT_ID"),
        "CTRADER_CLIENT_SECRET": credential_store.mask_secret("CTRADER_CLIENT_SECRET"),
        "CTRADER_ACCESS_TOKEN": credential_store.mask_secret("CTRADER_ACCESS_TOKEN"),
        "CTRADER_REFRESH_TOKEN": credential_store.mask_secret("CTRADER_REFRESH_TOKEN"),
        "GOOGLE_API_KEY": credential_store.mask_secret("GOOGLE_API_KEY"),
        "GROQ_API_KEY": credential_store.mask_secret("GROQ_API_KEY"),
        "dpapi_supported": True
    }

@router.post("/security/update-key")
async def update_security_key(req: UpdateKeyRequest):
    """Encrypts and stores a secret in the Windows DPAPI vault."""
    if not req.key or not req.value:
        raise HTTPException(status_code=400, detail="Key and Value are required")
    credential_store.set_secret(req.key, req.value.strip())
    db.log_audit(
        event_type="CREDENTIAL_UPDATED",
        actor="OperatorUI",
        details=f"Secure credential updated for key: {req.key}"
    )
    return {
        "status": "SUCCESS",
        "key": req.key,
        "masked": credential_store.mask_secret(req.key)
    }

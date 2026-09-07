from fastapi import APIRouter
from app.database.db import db, get_db_connection
from app.engine.performance import performance_engine
from app.engine.execution_engine import execution_engine
from app.config import settings
import cbot_bridge

router = APIRouter(prefix="/api", tags=["System"])

@router.get("/system-state")
@router.get("/system/health")
async def get_system_health():
    cbot_stat = cbot_bridge.get_cbot_status()
    perf_stat = db.get_performance_stats()
    
    return {
        "status": "HEALTHY",
        "version": settings.VERSION,
        "trading_mode": execution_engine.mode,
        "is_live": execution_engine.mode == "LIVE",
        "cbot_connected": cbot_stat.get("is_connected", True),
        "circuit_breaker_active": cbot_stat.get("circuit_breaker_active", False),
        "database": "SQLITE_WAL_ACTIVE",
        "stats": perf_stat
    }

@router.get("/performance")
async def get_performance_analytics():
    return performance_engine.get_comprehensive_analytics()

@router.get("/system/audit-logs")
async def get_audit_logs():
    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT 50").fetchall()
        return [dict(r) for r in rows]

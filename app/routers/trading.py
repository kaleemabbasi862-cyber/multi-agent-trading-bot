from fastapi import APIRouter
from pydantic import BaseModel
from app.engine.execution_engine import execution_engine
from app.database.db import db
import settings_manager

router = APIRouter(prefix="/api", tags=["Trading"])

class ModeChangeRequest(BaseModel):
    mode: str # 'PAPER', 'DEMO', 'LIVE'
    confirmed: bool = False

@router.get("/trading/mode")
async def get_trading_mode():
    return {
        "mode": execution_engine.mode,
        "is_live": execution_engine.mode == "LIVE"
    }

@router.post("/trading/mode")
async def set_trading_mode(req: ModeChangeRequest):
    return execution_engine.set_trading_mode(req.mode, req.confirmed)

@router.post("/auto-trade/toggle")
async def toggle_auto_trade():
    settings = settings_manager.load_settings()
    current = settings.get("auto_trade_enabled", False)
    settings["auto_trade_enabled"] = not current
    settings_manager.save_settings(settings)
    
    db.log_audit(
        event_type="AUTO_TRADE_TOGGLED",
        actor="User",
        details=f"Auto Trade set to {settings['auto_trade_enabled']}"
    )
    return {
        "status": "SUCCESS",
        "auto_trade_enabled": settings["auto_trade_enabled"]
    }

@router.get("/trades")
@router.get("/ledger")
async def get_trades(limit: int = 100):
    """Returns persistent broker and agent trades history from database."""
    return db.get_recent_trades(limit=limit)


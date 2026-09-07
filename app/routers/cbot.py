import os
from pathlib import Path
from fastapi import APIRouter, Response, Request
from fastapi.responses import PlainTextResponse
import cbot_bridge
from app.config import settings

router = APIRouter(prefix="/api/cbot", tags=["cBot Bridge"])

@router.post("/heartbeat")
@router.post("/stream")
async def cbot_heartbeat_stream(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    return cbot_bridge.update_heartbeat(data)

@router.get("/stream")
@router.get("/status")
async def get_cbot_status():
    return cbot_bridge.get_cbot_status()

@router.get("/orders")
@router.get("/pending")
@router.get("/pending-orders")
async def get_cbot_pending_orders():
    return cbot_bridge.get_pending_orders_for_cbot()

@router.post("/order-filled")
async def record_cbot_fill(request: Request):
    try:
        receipt = await request.json()
    except Exception:
        receipt = {}
    return cbot_bridge.record_cbot_execution(receipt)

@router.post("/close-position")
async def close_cbot_position(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    pos_id = payload.get("position_id")
    if pos_id:
        return cbot_bridge.queue_close_position(pos_id)
    return {"status": "ERROR", "message": "Missing position_id"}

@router.get("/download", response_class=PlainTextResponse)
async def download_cbot_source():
    cbot_path = Path(__file__).resolve().parent.parent.parent / "TradeTalkBridge.cs"
    if cbot_path.exists():
        with open(cbot_path, "r", encoding="utf-8") as f:
            return f.read()
    return "// TradeTalkBridge.cs not found"

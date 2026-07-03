# event_routes.py
# 事件相關的所有路由。用 APIRouter 分檔，main.py 保持乾淨
import os
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user
from event_service import handle_incoming_event, serialize_event, DeviceNotFoundError
from models import DetectEvent, Device, Staff

router = APIRouter()


# ── 機器驗證：判斷層帶 X-API-Key，跟 .env 的 EVENT_API_KEY 比對 ──
def require_api_key(x_api_key: Optional[str] = Header(None)):
    expected = os.environ.get("EVENT_API_KEY")
    if not expected or x_api_key != expected:
        raise HTTPException(status_code=401, detail="API key 無效或未提供")


# ── POST /events 收到的 JSON 格式 ──
# 注意：沒有 status 欄位——status 一律由後端設 pending，不接受外部指定（spec 規定）
class EventCreateRequest(BaseModel):
    device_id: int
    event_type: str
    clip_path: str
    detected_at: datetime
    snapshot_path: Optional[str] = None
    yolo_score: Optional[float] = None
    yolo_threshold: Optional[float] = None
    vlm_summary: Optional[str] = None
    vlm_confidence: Optional[float] = None
    recommended_action: Optional[str] = None
    incident_draft_notification: Optional[str] = None
    severity: Optional[Literal["low", "medium", "high"]] = None


# ════════════════════════════════════════════════════════
# POST /events（判斷層專用，API Key 驗證）
# ════════════════════════════════════════════════════════
# async def 的原因：廣播（put_nowait）要在事件迴圈執行緒上跑才安全
@router.post("/events", status_code=201, dependencies=[Depends(require_api_key)])
async def create_event(body: EventCreateRequest, db: Session = Depends(get_db)):
    try:
        # model_dump() 把 Pydantic 物件轉成 dict，交給共用處理函式
        return handle_incoming_event(db, body.model_dump())
    except DeviceNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ════════════════════════════════════════════════════════
# GET /events（登入即可）：事件列表，新到舊
# ════════════════════════════════════════════════════════
@router.get("/events")
def list_events(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # JOIN 裝置表，一次查好裝置名稱/位置，跟 SSE 廣播用同一個序列化函式
    rows = (
        db.query(DetectEvent, Device)
        .join(Device, DetectEvent.device_id == Device.device_id)
        .order_by(DetectEvent.detected_at.desc())
        .all()
    )
    return [serialize_event(event, device) for event, device in rows]


# ════════════════════════════════════════════════════════
# GET /staff（登入即可）：照護員名單（指派下拉選單用）
# ════════════════════════════════════════════════════════
@router.get("/staff")
def list_staff(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return [
        {"staff_id": s.staff_id, "staff_name": s.staff_name}
        for s in db.query(Staff).order_by(Staff.staff_id).all()
    ]

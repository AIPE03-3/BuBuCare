# event_routes.py
# 事件相關的所有路由。用 APIRouter 分檔，main.py 保持乾淨
import asyncio
import os
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import decode_access_token
from database import get_db
from dependencies import get_current_user
from event_service import handle_incoming_event, serialize_event, DeviceNotFoundError
from models import DetectEvent, Device, Staff
from sse import pool, format_sse

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


# ── PATCH /events/{id}/verdict 收到的 JSON 格式 ──
class VerdictRequest(BaseModel):
    verdict: Literal["true_alarm", "false_alarm"]
    staff_id: Optional[int] = None  # 只有判真跌倒時必填


# ════════════════════════════════════════════════════════
# PATCH /events/{event_id}/verdict（登入即可）：人工判定
# ════════════════════════════════════════════════════════
@router.patch("/events/{event_id}/verdict")
async def verdict_event(
    event_id: str,
    body: VerdictRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = db.query(DetectEvent).filter(DetectEvent.event_id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="事件不存在")

    # 狀態轉換守門：只有 pending 能被判定（409 = 請求沒錯，但跟目前狀態衝突）
    if event.status != "pending":
        raise HTTPException(status_code=409, detail="事件已被判定過")

    if body.verdict == "true_alarm":
        # 真跌倒：必須同時指派照護員
        if body.staff_id is None:
            raise HTTPException(status_code=422, detail="判定真跌倒必須指派照護員（staff_id）")
        staff = db.query(Staff).filter(Staff.staff_id == body.staff_id).first()
        if staff is None:
            raise HTTPException(status_code=400, detail=f"照護員 {body.staff_id} 不存在")
        event.status = "in_progress"
        event.verdict = "true_alarm"
        event.staff_id = body.staff_id
    else:
        # 誤報：不用派人，直接結案（staff_id 留空）
        event.status = "resolved"
        event.verdict = "false_alarm"

    db.commit()
    db.refresh(event)

    # 先存後播：commit 成功才廣播，讓所有中控站畫面同步
    device = db.query(Device).filter(Device.device_id == event.device_id).first()
    payload = serialize_event(event, device)
    pool.broadcast("event_updated", payload)
    return payload


# ════════════════════════════════════════════════════════
# PATCH /events/{event_id}/resolve（登入即可）：結案
# ════════════════════════════════════════════════════════
@router.patch("/events/{event_id}/resolve")
async def resolve_event(
    event_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = db.query(DetectEvent).filter(DetectEvent.event_id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="事件不存在")

    # 只有「處理中」能結案：pending 還沒判定、resolved 已經結過了
    if event.status != "in_progress":
        raise HTTPException(status_code=409, detail="只有處理中的事件可以結案")

    event.status = "resolved"
    db.commit()
    db.refresh(event)

    device = db.query(Device).filter(Device.device_id == event.device_id).first()
    payload = serialize_event(event, device)
    pool.broadcast("event_updated", payload)
    return payload


# ── SSE 專用驗證：EventSource 不能自訂 header，token 改放網址參數 ──
# 同一張 JWT，只是改插的位置；驗證邏輯用同一個 decode_access_token
def get_user_from_query_token(token: Optional[str] = Query(None)):
    if token is None:
        raise HTTPException(status_code=401, detail="缺少 token")
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="token 無效或過期")
    return payload


# ════════════════════════════════════════════════════════
# GET /stream（登入即可，token 放 query）：SSE 長連線
# ════════════════════════════════════════════════════════
@router.get("/stream")
async def stream(current_user: dict = Depends(get_user_from_query_token)):
    q = pool.register()  # 進來就掛一個信箱到連線池

    async def event_generator():
        try:
            while True:
                try:
                    # 守在自己的信箱旁等訊息，最多等 15 秒
                    message = await asyncio.wait_for(q.get(), timeout=15)
                    yield format_sse(message)
                except asyncio.TimeoutError:
                    # 15 秒沒事件 → 送心跳，防止中間網路設備掐斷「太久沒動靜」的連線
                    yield ": ping\n\n"
        finally:
            # 瀏覽器關掉/斷線/F5 → generator 被取消 → 把信箱移出連線池
            pool.unregister(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# backend/events/router.py
# 事件相關的所有路由。用 APIRouter 分檔，main.py 保持乾淨
import asyncio
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, aliased, selectinload

from core import s3
from core.auth import decode_access_token
from core.config import EVENT_API_KEY
from core.database import get_db
from core.dependencies import get_current_user
from core.models import DetectEvent, Device, User
from events.service import handle_incoming_event, operator_names, serialize_event, watch_delivery, DeviceNotFoundError
from events.sse import pool, format_sse

router = APIRouter()


# ── 機器驗證：判斷層帶 X-API-Key，跟 .env 的 EVENT_API_KEY 比對 ──
def require_api_key(x_api_key: Optional[str] = Header(None)):
    if not EVENT_API_KEY or x_api_key != EVENT_API_KEY:
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
    vlm_summary: Optional[str] = None
    # agent P2：LangGraph agent（目前 shadow）的建議判斷，僅供人工複判參考；三欄皆選填，
    # 舊格式訊息（無此三欄）照常建檔，欄位落 NULL
    ai_verdict: Optional[Literal["true_alarm", "false_alarm"]] = None
    ai_confidence: Optional[float] = None
    ai_reasoning: Optional[str] = None


# ════════════════════════════════════════════════════════
# POST /events（判斷層專用，API Key 驗證）
# ════════════════════════════════════════════════════════
# async def 的原因：廣播（put_nowait）要在事件迴圈執行緒上跑才安全
@router.post("/events", status_code=201, dependencies=[Depends(require_api_key)])
async def create_event(body: EventCreateRequest, db: Session = Depends(get_db)):
    try:
        # model_dump() 把 Pydantic 物件轉成 dict，交給共用處理函式
        payload = handle_incoming_event(db, body.model_dump())
    except DeviceNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # 廣播後啟動背景任務盯送達。放這裡而非 handle_incoming_event 內：
    # 路由是 async、有 event loop；handle_incoming_event 是同步、被測試直接呼叫時沒 loop
    asyncio.create_task(watch_delivery(payload["event_id"]))
    return payload


# ════════════════════════════════════════════════════════
# POST /events/{event_id}/ack（登入即可）：前端收到 SSE 後自動回報收到
# ════════════════════════════════════════════════════════
@router.post("/events/{event_id}/ack")
def ack_event(
    event_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = db.query(DetectEvent).filter(DetectEvent.event_id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="事件不存在")

    # 只蓋第一次：已有值就不動，保留最早的送達時間（重推可能觸發多次 ack）
    # 送達狀態記在後端 DB，給重推計時器判斷用（整套推送→ack→重推是 at-least-once 保證送達）
    # 前端打完 ack 不需要處理回應，回個小確認即可
    if event.notified_at is None:
        event.notified_at = datetime.now()
        db.commit()

    return {"status": "ok"}


# ════════════════════════════════════════════════════════
# GET /events（登入即可）：事件列表，新到舊
# ════════════════════════════════════════════════════════
@router.get("/events")
def list_events(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # JOIN 裝置表拿裝置名稱/位置；再 LEFT JOIN 兩份 user_account（判定者、結案者）夾帶處理人姓名，
    # 全部一次查好、不逐筆補查（避免 N+1）。verdict_by/resolved_by 可能為空，故用 outerjoin 不濾掉事件。
    # selectinload：所有事件的通報單一次撈完，避免 serialize_event 每筆各查一次（N+1）
    verdict_user = aliased(User)
    resolved_user = aliased(User)
    rows = (
        db.query(DetectEvent, Device, verdict_user.full_name, resolved_user.full_name)
        .join(Device, DetectEvent.device_id == Device.device_id)
        .outerjoin(verdict_user, DetectEvent.verdict_by == verdict_user.employee_id)
        .outerjoin(resolved_user, DetectEvent.resolved_by == resolved_user.employee_id)
        .options(selectinload(DetectEvent.reports))
        .order_by(DetectEvent.detected_at.desc())
        .all()
    )
    return [
        serialize_event(event, device, verdict_by_name, resolved_by_name)
        for event, device, verdict_by_name, resolved_by_name in rows
    ]


# ── PATCH /events/{id}/verdict 收到的 JSON 格式 ──
# 不收任何「人」的欄位：誰點的誰負責，操作員由後端從 JWT 記錄
class VerdictRequest(BaseModel):
    verdict: Literal["true_alarm", "false_alarm"]


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

    operator = current_user["sub"]  # JWT 的 sub 就是員編：誰按的誰負責
    if body.verdict == "true_alarm":
        event.status = "in_progress"
        event.verdict = "true_alarm"
        event.verdict_by = operator
    else:
        # 誤報：判定即結案，同一個按鈕同時記判定者與結案者
        event.status = "resolved"
        event.verdict = "false_alarm"
        event.verdict_by = operator
        event.resolved_by = operator

    db.commit()
    db.refresh(event)

    # 先存後播：commit 成功才廣播，讓所有中控站畫面同步
    device = db.query(Device).filter(Device.device_id == event.device_id).first()
    verdict_by_name, resolved_by_name = operator_names(db, event)
    payload = serialize_event(event, device, verdict_by_name, resolved_by_name)
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
    event.resolved_by = current_user["sub"]  # 誰按結案誰負責
    db.commit()
    db.refresh(event)

    device = db.query(Device).filter(Device.device_id == event.device_id).first()
    verdict_by_name, resolved_by_name = operator_names(db, event)
    payload = serialize_event(event, device, verdict_by_name, resolved_by_name)
    pool.broadcast("event_updated", payload)
    return payload


# ════════════════════════════════════════════════════════
# GET /events/{event_id}/media（登入即可）：換發S3影片/截圖限時網址
# ════════════════════════════════════════════════════════
@router.get("/events/{event_id}/media")
def get_event_media(
    event_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = db.query(DetectEvent).filter(DetectEvent.event_id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="事件不存在")
    # 點開當下才現發，保證新鮮不過期；非 s3:// 的欄位（含空 snapshot）自然回 null
    return {
        "clip_url": s3.generate_presigned_url(event.clip_path),
        "snapshot_url": s3.generate_presigned_url(event.snapshot_path),
    }


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

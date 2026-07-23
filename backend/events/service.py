# backend/events/service.py
# 事件「處理」核心：存 DB + 廣播。跟「入口」（POST /events、未來的 Kafka consumer）拆開，
# Kafka 接上時直接呼叫 handle_incoming_event()，這裡零改動
import asyncio

from sqlalchemy.orm import Session

from backend.core.database import SessionLocal
from backend.core.models import DetectEvent, Device, User
from backend.events.sse import pool


class DeviceNotFoundError(Exception):
    # 事件指到不存在的裝置。入口層自己決定怎麼回應（HTTP 入口回 400）
    pass


def serialize_event(
    event: DetectEvent,
    device: Device,
    verdict_by_name: str | None = None,
    resolved_by_name: str | None = None,
) -> dict:
    # 事件的統一 JSON 結構：SSE 廣播和 GET /events 都用這一個函式，
    # 前端只需寫一套顯示邏輯。裝置名稱/位置直接夾帶，前端不用再查。
    #
    # 處理人顯示名（verdict_by_name / resolved_by_name）跟 device 一樣「由呼叫端事先查好再傳進來」，
    # 本函式只負責組裝、不碰資料庫：列表端用 JOIN 一次撈、單筆端用 operator_names() 取（見下方）。
    #
    # ⚠ event.reports 會觸發延遲載入（多發一次 SQL）。一次序列化多筆事件時，
    #   查詢端要先 selectinload(DetectEvent.reports)，否則每筆各查一次（N+1）
    latest_report = event.reports[-1] if event.reports else None

    return {
        "event_id": event.event_id,
        "device_id": event.device_id,
        "device_name": device.device_name,
        # 讀事件凍住的位置（event.location），不看裝置現況；事件沒凍到位置時回 None
        "location": event.location.location_name if event.location else None,
        "event_type": event.event_type,
        "status": event.status,
        "verdict": event.verdict,
        "clip_path": event.clip_path,
        "snapshot_path": event.snapshot_path,
        "detected_at": event.detected_at.isoformat(),
        # 讓前端/除錯看得到送達狀態：None = 還沒被 ack
        "notified_at": event.notified_at.isoformat() if event.notified_at else None,
        "verdict_by": event.verdict_by,
        "verdict_by_name": verdict_by_name,
        "resolved_by": event.resolved_by,
        "resolved_by_name": resolved_by_name,
        # 通報階段＝最新一筆通報單的類型；兩者皆 None 代表這個事件還沒有任何通報單
        "report_stage": latest_report.report_type if latest_report else None,
        "last_report_at": latest_report.created_at.isoformat() if latest_report else None,
        "company_id": event.company_id,
        "yolo_score": event.yolo_score,
        "vlm_summary": event.vlm_summary,
    }


def operator_names(db: Session, event: DetectEvent) -> tuple[str | None, str | None]:
    # 依單筆 event 的 verdict_by / resolved_by 員編，查 user_account 的 full_name。
    # 給「只動一筆事件」的呼叫端用（判定 / 結案）；列表端自己用 JOIN 一次撈好、不走這裡。
    # 回傳 (判定者名, 結案者名)，查不到的為 None（前端會自動退回顯示員編）。
    ids = {eid for eid in (event.verdict_by, event.resolved_by) if eid}
    if not ids:
        return None, None
    names = dict(
        db.query(User.employee_id, User.full_name)
        .filter(User.employee_id.in_(ids))
        .all()
    )
    return names.get(event.verdict_by), names.get(event.resolved_by)


def is_delivered(db: Session, event_id: str) -> bool:
    # 重推的停止判斷。三種情況都算「不用再推」：
    #   1. notified_at 有值 → 前端已回報收到
    #   2. status 離開 pending → 有人已在處理，等於也送達了
    #   3. 事件不存在 → 已被刪或查無，沒東西可推
    event = db.query(DetectEvent).filter(DetectEvent.event_id == event_id).first()
    if event is None:
        return True
    if event.notified_at is not None:
        return True
    if event.status != "pending":
        return True
    return False


def rebroadcast_event(db: Session, event_id: str) -> None:
    # 重推：重查事件與裝置，沿用 event_created 事件名再廣播一次
    # （前端以 event_id 去重，收到同一筆只會更新該列、不會重複顯示）
    event = db.query(DetectEvent).filter(DetectEvent.event_id == event_id).first()
    if event is None:
        return
    device = db.query(Device).filter(Device.device_id == event.device_id).first()
    pool.broadcast("event_created", serialize_event(event, device))


async def watch_delivery(
    event_id: str,
    *,
    session_factory=SessionLocal,
    interval: float = 10.0,
    max_attempts: int = 3,
) -> None:
    # 事件建立後盯送達：每 interval 秒檢查一次，未送達就重推一次，最多 max_attempts 次
    # session_factory 可注入：正式用 SessionLocal，測試傳測試 DB 的工廠
    for _ in range(max_attempts):
        await asyncio.sleep(interval)
        db = session_factory()  # 背景任務不在請求裡，要開自己的 session
        try:
            if is_delivered(db, event_id):
                return
            rebroadcast_event(db, event_id)
        finally:
            db.close()


def handle_incoming_event(db: Session, data: dict) -> dict:
    # 1. 先確認裝置存在（不存在就什麼都不做）
    device = db.query(Device).filter(Device.device_id == data["device_id"]).first()
    if device is None:
        raise DeviceNotFoundError(f"裝置 {data['device_id']} 不存在")

    # 2. 先存 DB（status 一律後端設 pending，company_id / location_id 都跟著裝置當下狀態凍一份）
    event = DetectEvent(**data, company_id=device.company_id, location_id=device.location_id)
    db.add(event)
    db.commit()
    db.refresh(event)

    # 3. 存成功才廣播（資料庫是唯一真相；存失敗上面就丟例外，不會走到這行）
    payload = serialize_event(event, device)
    pool.broadcast("event_created", payload)
    return payload

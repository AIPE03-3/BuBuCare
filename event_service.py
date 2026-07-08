# event_service.py
# 事件「處理」核心：存 DB + 廣播。跟「入口」（POST /events、未來的 Kafka consumer）拆開，
# Kafka 接上時直接呼叫 handle_incoming_event()，這裡零改動
import asyncio

from sqlalchemy.orm import Session

from database import SessionLocal
from models import DetectEvent, Device
from sse import pool


class DeviceNotFoundError(Exception):
    # 事件指到不存在的裝置。入口層自己決定怎麼回應（HTTP 入口回 400）
    pass


def serialize_event(event: DetectEvent, device: Device) -> dict:
    # 事件的統一 JSON 結構：SSE 廣播和 GET /events 都用這一個函式，
    # 前端只需寫一套顯示邏輯。裝置名稱/位置直接夾帶，前端不用再查
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
        "staff_id": event.staff_id,
        "company_id": event.company_id,
        "yolo_score": event.yolo_score,
        "yolo_threshold": event.yolo_threshold,
        "vlm_summary": event.vlm_summary,
        "severity": event.severity,
    }


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

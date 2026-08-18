# 測事件處理核心：入口（POST/Kafka）共用的 handle_incoming_event()
from datetime import datetime
import pytest

from events.service import handle_incoming_event, DeviceNotFoundError, serialize_event
from core.models import DetectEvent, DetectEventReport, Device, Location
from events.sse import pool

VALID_DATA = {
    "device_id": 1,
    "event_type": "fall",
    "clip_path": "s3://clips/e1.mp4",
    "detected_at": datetime(2026, 7, 2, 14, 30),
}


def test_存DB成功並廣播event_created(db_session):
    q = pool.register()
    try:
        payload = handle_incoming_event(db_session, dict(VALID_DATA))
    finally:
        pool.unregister(q)

    # 存進 DB 了
    assert db_session.query(DetectEvent).count() == 1
    # 廣播了，且訊息裡帶完整事件（含裝置名稱，前端零額外請求）
    msg = q.get_nowait()
    assert msg["event"] == "event_created"
    assert msg["data"]["device_name"] == "交誼廳-01"
    assert msg["data"]["location"] == "交誼廳"
    assert msg["data"]["status"] == "pending"
    # 回傳值和廣播內容是同一包
    assert payload["event_id"] == msg["data"]["event_id"]


def test_裝置不存在_不存DB_不廣播(db_session):
    q = pool.register()
    try:
        with pytest.raises(DeviceNotFoundError):
            handle_incoming_event(db_session, {**VALID_DATA, "device_id": 999})
    finally:
        pool.unregister(q)

    assert db_session.query(DetectEvent).count() == 0  # 什麼都沒存
    assert q.empty()                                    # 什麼都沒廣播


def test_事件位置凍結_裝置事後搬走也不變(db_session):
    # 事件發生時，裝置 1 在 location 1（交誼廳）→ 位置被凍進事件
    payload = handle_incoming_event(db_session, dict(VALID_DATA))
    assert payload["location"] == "交誼廳"

    # 事後把裝置 1 搬到新區域「走廊」（location 2）
    db_session.add(Location(location_id=2, location_name="走廊", company_id=1))
    device = db_session.query(Device).filter(Device.device_id == 1).first()
    device.location_id = 2
    db_session.commit()

    # 重新取出那筆舊事件並序列化：即使傳入的是「已搬到走廊」的裝置，
    # 位置仍是發生當下凍住的「交誼廳」，證明顯示讀的是事件凍值、不是裝置現況
    event = db_session.query(DetectEvent).first()
    assert serialize_event(event, device)["location"] == "交誼廳"


def test_serialize包含notified_at預設None(db_session, make_event):
    event = make_event()
    device = db_session.query(Device).filter(Device.device_id == 1).first()
    data = serialize_event(event, device)
    assert "notified_at" in data
    assert data["notified_at"] is None


def test_serialize尚無通報單時通報階段為None(db_session, make_event):
    event = make_event()
    device = db_session.query(Device).filter(Device.device_id == 1).first()
    data = serialize_event(event, device)
    assert data["report_stage"] is None
    assert data["last_report_at"] is None


def test_serialize帶最新一筆通報單的階段與時間(db_session, make_event):
    # 初報 → 續報，通報階段要跟著走到最新那筆（不是第一筆、也不是筆數）
    event = make_event()
    db_session.add(DetectEventReport(
        event_id=event.event_id, report_type="initial", form={},
        created_by="alice", created_at=datetime(2026, 7, 2, 15, 0),
    ))
    db_session.add(DetectEventReport(
        event_id=event.event_id, report_type="follow_up", form={},
        created_by="alice", created_at=datetime(2026, 7, 3, 9, 0),
    ))
    db_session.commit()
    db_session.refresh(event)

    device = db_session.query(Device).filter(Device.device_id == 1).first()
    data = serialize_event(event, device)
    assert data["report_stage"] == "follow_up"
    assert data["last_report_at"] == "2026-07-03T09:00:00"


# ── agent P2：AI 建議判斷欄位 ──

def test_serialize舊事件無ai欄位時全為None(db_session, make_event):
    event = make_event()  # 不帶 ai_* kwargs，模擬既有事件（欄位補上前建立的）
    device = db_session.query(Device).filter(Device.device_id == 1).first()
    data = serialize_event(event, device)
    assert data["ai_verdict"] is None
    assert data["ai_confidence"] is None
    assert data["ai_reasoning"] is None


def test_serialize帶ai建議時原樣輸出(db_session, make_event):
    event = make_event(
        ai_verdict="false_alarm",
        ai_confidence=0.8,
        ai_reasoning="現場沒有任何人存在，因此可以確定並非真實的跌倒事件。",
    )
    device = db_session.query(Device).filter(Device.device_id == 1).first()
    data = serialize_event(event, device)
    assert data["ai_verdict"] == "false_alarm"
    assert data["ai_confidence"] == 0.8
    assert data["ai_reasoning"] == "現場沒有任何人存在，因此可以確定並非真實的跌倒事件。"

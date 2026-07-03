# 測事件處理核心：入口（POST/Kafka）共用的 handle_incoming_event()
from datetime import datetime
import pytest

from event_service import handle_incoming_event, DeviceNotFoundError
from models import DetectEvent
from sse import pool

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

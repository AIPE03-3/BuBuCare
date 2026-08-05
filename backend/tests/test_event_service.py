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
        payload, created = handle_incoming_event(db_session, dict(VALID_DATA))
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
    assert created is True  # 新建，入口層據此回 201 並啟動送達盯梢


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
    payload, _ = handle_incoming_event(db_session, dict(VALID_DATA))
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


# ── 同一起事件的補寫（agent 二審完成後把判讀文字補回快速道事件）──
#
# 背景：高信心跌倒走快速道、依規格不等 VLM（docs/ARCHITECTURE.md §2），所以 vlm_summary
# 是邊緣端寫死的罐頭字串。開了 FAST_TRACK_VLM_ENRICH 後，同一筆會再送一份進二審佇列，
# agent 判讀完把結果送回 processed-reports —— 那一則必須補寫既有那筆，不能變成新事件。

FAST_TRACK_DATA = {
    **VALID_DATA,
    "vlm_summary": "【緊急通報】邊緣端偵測到嚴重跌倒！請立刻前往救援。",
}
ENRICHED_DATA = {
    **VALID_DATA,
    "vlm_summary": "畫面中一位長者呈大字狀仰躺於地面，四肢張開、無自主起身動作。",
    "ai_verdict": "true_alarm",
    "ai_confidence": 0.95,
    "ai_reasoning": "姿態與地面接觸面積符合跌倒特徵。",
}


def test_同一起事件補寫_不新增只更新且廣播event_updated(db_session):
    handle_incoming_event(db_session, dict(FAST_TRACK_DATA))

    q = pool.register()
    try:
        payload, created = handle_incoming_event(db_session, dict(ENRICHED_DATA))
    finally:
        pool.unregister(q)

    assert created is False
    assert db_session.query(DetectEvent).count() == 1  # 沒有多出第二筆
    msg = q.get_nowait()
    assert msg["event"] == "event_updated"             # 不是 event_created，前端才不會再彈一次
    assert payload["vlm_summary"] == ENRICHED_DATA["vlm_summary"]
    assert payload["ai_verdict"] == "true_alarm"
    assert payload["ai_confidence"] == 0.95
    assert payload["ai_reasoning"] == "姿態與地面接觸面積符合跌倒特徵。"


def test_補寫不覆蓋人工操作(db_session):
    # 值班人員在補寫抵達前就按了「接手處理」（補寫是事發約 35 秒後才到）
    handle_incoming_event(db_session, dict(FAST_TRACK_DATA))
    event = db_session.query(DetectEvent).first()
    event.status = "in_progress"
    event.verdict = "true_alarm"
    event.verdict_by = "E001"
    event.notified_at = datetime(2026, 7, 2, 14, 30, 5)
    db_session.commit()

    handle_incoming_event(db_session, dict(ENRICHED_DATA))

    db_session.refresh(event)
    assert event.status == "in_progress"                       # 沒被退回 pending
    assert event.verdict == "true_alarm"
    assert event.verdict_by == "E001"
    assert event.notified_at == datetime(2026, 7, 2, 14, 30, 5)
    assert event.vlm_summary == ENRICHED_DATA["vlm_summary"]   # 但判讀文字有補上


def test_補寫沒帶到的欄位保留原值不被None洗掉(db_session):
    handle_incoming_event(db_session, {**FAST_TRACK_DATA, "ai_reasoning": "邊緣端初判"})
    # agent 判不出 verdict 時 ai_verdict / ai_reasoning 會是 None，不該把既有值清空
    handle_incoming_event(db_session, {
        **VALID_DATA,
        "vlm_summary": "補上的判讀文字",
        "ai_verdict": None,
        "ai_reasoning": None,
    })
    event = db_session.query(DetectEvent).first()
    assert event.vlm_summary == "補上的判讀文字"
    assert event.ai_reasoning == "邊緣端初判"


def test_不同時間的事件仍各自成案(db_session):
    # 認定「同一起事件」靠 device_id + detected_at + event_type，時間不同就是兩起
    handle_incoming_event(db_session, dict(VALID_DATA))
    handle_incoming_event(db_session, {**VALID_DATA, "detected_at": datetime(2026, 7, 2, 14, 31)})
    assert db_session.query(DetectEvent).count() == 2

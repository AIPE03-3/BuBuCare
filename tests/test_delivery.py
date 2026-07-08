# 測送達判斷 + 重推邏輯
from datetime import datetime

from event_service import is_delivered


def test_is_delivered_notified有值即已送達(db_session, make_event):
    event = make_event(notified_at=datetime(2026, 7, 2, 14, 31))
    assert is_delivered(db_session, event.event_id) is True


def test_is_delivered_status非pending即已送達(db_session, make_event):
    event = make_event(status="in_progress", verdict="true_alarm", staff_id=1)
    assert is_delivered(db_session, event.event_id) is True


def test_is_delivered_pending且未notified為未送達(db_session, make_event):
    event = make_event()  # 預設 pending、notified_at None
    assert is_delivered(db_session, event.event_id) is False


def test_is_delivered_事件不存在視為已送達不重推(db_session):
    assert is_delivered(db_session, "no-such-id") is True

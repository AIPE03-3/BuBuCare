# 測 POST /events/{id}/ack：前端自動回報收到
from datetime import datetime

from backend.core.models import DetectEvent


def test_未登入_401(client, make_event):
    event = make_event()
    res = client.post(f"/events/{event.event_id}/ack")
    assert res.status_code == 401


def test_ack成功蓋章並回200(client, auth_headers, make_event, db_session):
    event = make_event()
    assert event.notified_at is None
    res = client.post(f"/events/{event.event_id}/ack", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    db_session.expire_all()
    updated = db_session.query(DetectEvent).filter_by(event_id=event.event_id).first()
    assert updated.notified_at is not None


def test_重複ack保留第一次時間(client, auth_headers, make_event, db_session):
    first = datetime(2026, 7, 2, 14, 31)
    event = make_event(notified_at=first)
    res = client.post(f"/events/{event.event_id}/ack", headers=auth_headers)
    assert res.status_code == 200
    db_session.expire_all()
    updated = db_session.query(DetectEvent).filter_by(event_id=event.event_id).first()
    assert updated.notified_at == first


def test_事件不存在_404(client, auth_headers):
    res = client.post("/events/no-such-id/ack", headers=auth_headers)
    assert res.status_code == 404

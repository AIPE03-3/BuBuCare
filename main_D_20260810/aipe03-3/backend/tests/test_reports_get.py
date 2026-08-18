# test_reports_get.py
# 測試 GET /events/{event_id}/reports：查某事件全部通報單
# 排序契約：舊→新（前端 getLatestReport 取陣列最後一筆當最新，順序錯了會默默拿到舊資料）

from datetime import datetime

from core.models import DetectEventReport


def _insert_report(db_session, event_id, report_type, created_at):
    # 直接塞 DB 指定 created_at，排序測試才有確定的先後
    report = DetectEventReport(
        event_id=event_id, report_type=report_type,
        form={"note": report_type}, created_by="alice", created_at=created_at,
    )
    db_session.add(report)
    db_session.commit()


def test_reports_sorted_old_to_new(client, auth_headers, make_event, db_session):
    event = make_event()
    # 故意亂序塞入：新的先塞、舊的後塞
    _insert_report(db_session, event.event_id, "final", datetime(2026, 7, 22, 9, 0))
    _insert_report(db_session, event.event_id, "initial", datetime(2026, 7, 20, 9, 0))
    _insert_report(db_session, event.event_id, "follow_up", datetime(2026, 7, 21, 9, 0))

    res = client.get(f"/events/{event.event_id}/reports", headers=auth_headers)
    assert res.status_code == 200
    types = [r["report_type"] for r in res.json()]
    assert types == ["initial", "follow_up", "final"]  # 回應照時間舊→新


def test_no_reports_returns_empty_list(client, auth_headers, make_event):
    event = make_event()
    res = client.get(f"/events/{event.event_id}/reports", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []


def test_get_reports_unknown_event_returns_404(client, auth_headers):
    res = client.get("/events/no-such-event/reports", headers=auth_headers)
    assert res.status_code == 404


def test_get_reports_only_own_event(client, auth_headers, make_event, db_session):
    # 只回該事件的通報單，別的事件的不混進來
    event_a = make_event()
    event_b = make_event()
    _insert_report(db_session, event_a.event_id, "initial", datetime(2026, 7, 20, 9, 0))
    _insert_report(db_session, event_b.event_id, "initial", datetime(2026, 7, 20, 9, 0))

    res = client.get(f"/events/{event_a.event_id}/reports", headers=auth_headers)
    assert len(res.json()) == 1
    assert res.json()[0]["event_id"] == event_a.event_id


def test_get_reports_requires_login(client, make_event):
    event = make_event()
    res = client.get(f"/events/{event.event_id}/reports")
    assert res.status_code == 401

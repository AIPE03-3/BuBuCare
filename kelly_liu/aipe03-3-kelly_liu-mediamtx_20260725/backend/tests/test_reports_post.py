# test_reports_post.py
# 測試 POST /events/{event_id}/reports：存通報單
# form 整包 JSON 原樣保管；created_by 由後端從 JWT 記（誰存的誰負責）

from backend.core.models import DetectEventReport

FORM = {"caseName": "王小明", "reportType": "初報", "handling": ["送醫治療"]}


def test_save_report_returns_201(client, auth_headers, make_event):
    event = make_event()
    res = client.post(f"/events/{event.event_id}/reports",
                      json={"report_type": "initial", "form": FORM},
                      headers=auth_headers)
    assert res.status_code == 201
    data = res.json()
    assert data["event_id"] == event.event_id
    assert data["report_type"] == "initial"
    assert data["form"] == FORM                 # 整包原樣存、原樣回
    assert data["created_by"] == "alice"        # 從 JWT 記，不是前端帶的
    assert data["created_at"] is not None


def test_reports_accumulate_not_overwrite(client, auth_headers, make_event, db_session):
    # 同事件存兩筆 → 兩筆都在（不覆蓋），且同類型也可重複
    event = make_event()
    client.post(f"/events/{event.event_id}/reports",
                json={"report_type": "initial", "form": FORM}, headers=auth_headers)
    client.post(f"/events/{event.event_id}/reports",
                json={"report_type": "follow_up", "form": FORM}, headers=auth_headers)

    count = db_session.query(DetectEventReport).filter(
        DetectEventReport.event_id == event.event_id).count()
    assert count == 2


def test_save_report_unknown_event_returns_404(client, auth_headers):
    res = client.post("/events/no-such-event/reports",
                      json={"report_type": "initial", "form": FORM},
                      headers=auth_headers)
    assert res.status_code == 404


def test_invalid_report_type_returns_422(client, auth_headers, make_event):
    event = make_event()
    res = client.post(f"/events/{event.event_id}/reports",
                      json={"report_type": "第一次通報", "form": FORM},  # 要收英文 enum
                      headers=auth_headers)
    assert res.status_code == 422


def test_save_report_requires_login(client, make_event):
    event = make_event()
    res = client.post(f"/events/{event.event_id}/reports",
                      json={"report_type": "initial", "form": FORM})
    assert res.status_code == 401

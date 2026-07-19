# 測 PATCH /events/{id}/verdict：值班人員判定真跌倒/誤報
# 2026-07-19 改版：誰點的誰負責——操作員由後端從 JWT 記錄，body 不再帶人
from backend.events.sse import pool


def test_未登入_401(client, make_event):
    event = make_event()
    res = client.patch(f"/events/{event.event_id}/verdict", json={"verdict": "false_alarm"})
    assert res.status_code == 401


def test_判誤報_直接結案(client, auth_headers, make_event):
    event = make_event()  # 預設 status=pending

    res = client.patch(
        f"/events/{event.event_id}/verdict",
        json={"verdict": "false_alarm"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "resolved"      # 誤報直接結案
    assert data["verdict"] == "false_alarm"
    assert data["verdict_by"] == "alice"     # auth_headers 是 alice 的 token
    assert data["resolved_by"] == "alice"    # 一鍵結案：判定者同時記為結案者


def test_判真跌倒_進入處理中並記錄判定者(client, auth_headers, make_event):
    event = make_event()

    res = client.patch(
        f"/events/{event.event_id}/verdict",
        json={"verdict": "true_alarm"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "in_progress"
    assert data["verdict"] == "true_alarm"
    assert data["verdict_by"] == "alice"
    assert data["resolved_by"] is None       # 還沒結案


def test_已判定過再判_409(client, auth_headers, make_event):
    # 造一筆已經判定過的事件（另一個值班人員搶先處理了）
    event = make_event(status="in_progress", verdict="true_alarm", verdict_by="boss")
    res = client.patch(
        f"/events/{event.event_id}/verdict",
        json={"verdict": "false_alarm"},
        headers=auth_headers,
    )
    assert res.status_code == 409


def test_事件不存在_404(client, auth_headers):
    res = client.patch(
        "/events/00000000-0000-0000-0000-000000000000/verdict",
        json={"verdict": "false_alarm"},
        headers=auth_headers,
    )
    assert res.status_code == 404


def test_判定成功會廣播event_updated(client, auth_headers, make_event):
    event = make_event()
    q = pool.register()
    try:
        client.patch(
            f"/events/{event.event_id}/verdict",
            json={"verdict": "false_alarm"},
            headers=auth_headers,
        )
    finally:
        pool.unregister(q)

    msg = q.get_nowait()
    assert msg["event"] == "event_updated"
    assert msg["data"]["status"] == "resolved"

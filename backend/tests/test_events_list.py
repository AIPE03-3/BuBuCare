# 測 GET /events：前端進頁面時拉的事件列表（含歷史）
from datetime import datetime


def test_未登入_401(client):
    res = client.get("/events")
    assert res.status_code == 401


def test_列表依偵測時間新到舊(client, auth_headers, make_event):
    make_event(detected_at=datetime(2026, 7, 1, 10, 0))   # 舊
    make_event(detected_at=datetime(2026, 7, 2, 15, 0))   # 新

    res = client.get("/events", headers=auth_headers)
    assert res.status_code == 200
    events = res.json()
    assert len(events) == 2
    assert events[0]["detected_at"] > events[1]["detected_at"]  # 新的排前面


def test_列表帶裝置名稱(client, auth_headers, make_event):
    make_event()
    res = client.get("/events", headers=auth_headers)
    assert res.json()[0]["device_name"] == "交誼廳-01"
    assert res.json()[0]["location"] == "交誼廳"

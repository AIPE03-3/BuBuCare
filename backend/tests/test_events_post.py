# 測 POST /events：判斷層送事件進來的入口（機器對機器，用 API Key 驗證）
API_KEY_HEADERS = {"X-API-Key": "test-api-key"}  # conftest.py 設定的測試 key

VALID_BODY = {
    "device_id": 1,
    "event_type": "fall",
    "clip_path": "s3://clips/e1.mp4",
    "detected_at": "2026-07-02T14:30:00",
}


def test_沒帶key_401(client):
    res = client.post("/events", json=VALID_BODY)
    assert res.status_code == 401


def test_key錯誤_401(client):
    res = client.post("/events", json=VALID_BODY, headers={"X-API-Key": "wrong-key"})
    assert res.status_code == 401


def test_正常建立_201(client):
    res = client.post("/events", json=VALID_BODY, headers=API_KEY_HEADERS)
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "pending"       # 後端一律設 pending
    assert data["verdict"] is None
    assert data["device_name"] == "交誼廳-01"  # 序列化直接夾帶裝置資訊


def test_裝置不存在_400(client):
    res = client.post("/events", json={**VALID_BODY, "device_id": 999}, headers=API_KEY_HEADERS)
    assert res.status_code == 400


def test_缺必填欄位_422(client):
    body = dict(VALID_BODY)
    del body["detected_at"]  # detected_at 是必填
    res = client.post("/events", json=body, headers=API_KEY_HEADERS)
    assert res.status_code == 422


# ── clip_path：Pydantic 層放行（hazard 沒有影片），業務規則在 service 層擋 ──

def test_跌倒缺clip_path_400(client):
    """跌倒有明確事發時刻、一定錄得到片段，沒帶就是判斷層漏送，當場擋下。"""
    body = dict(VALID_BODY)
    del body["clip_path"]
    res = client.post("/events", json=body, headers=API_KEY_HEADERS)
    assert res.status_code == 400


def test_hazard缺clip_path_201(client):
    """潛在危險是持續狀態（桌上有把刀），沒有「事發前後 N 秒」可錄，只有快照。"""
    body = {
        "device_id": 1,
        "event_type": "hazard",
        "detected_at": "2026-07-28T09:00:00",
        "snapshot_path": "s3://snaps/knife.jpg",
        "hazard_object": "knife",
    }
    res = client.post("/events", json=body, headers=API_KEY_HEADERS)
    assert res.status_code == 201
    data = res.json()
    assert data["event_type"] == "hazard"
    assert data["clip_path"] is None
    assert data["hazard_object"] == "knife"   # 存 COCO class name 原字串，不翻中文

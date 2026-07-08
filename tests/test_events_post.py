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
    del body["clip_path"]  # clip_path 是必填
    res = client.post("/events", json=body, headers=API_KEY_HEADERS)
    assert res.status_code == 422

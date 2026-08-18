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


# ── agent P2：AI 建議判斷（ai_verdict/ai_confidence/ai_reasoning）三路徑 ──
# 三欄皆選填，agent 目前仍是 shadow 模式，這裡只測後端「記錄」與「顯示」，
# 不代表已經接上 agent 即時寫入（見 docs/CHANGELOG-STAGES.md 第 6 項）。

def test_舊格式訊息無ai欄位_照常建檔且ai欄位為null(client):
    # VALID_BODY 本來就沒有 ai_* 三欄，模擬舊格式訊息（vlm_worker 送的巡檢/既有事件）
    res = client.post("/events", json=VALID_BODY, headers=API_KEY_HEADERS)
    assert res.status_code == 201
    data = res.json()
    assert data["ai_verdict"] is None
    assert data["ai_confidence"] is None
    assert data["ai_reasoning"] is None


def test_ai建議true_alarm_正確記錄且不影響人工verdict(client):
    body = {
        **VALID_BODY,
        "ai_verdict": "true_alarm",
        "ai_confidence": 0.92,
        "ai_reasoning": "畫面中人物平躺在地，姿態符合跌倒特徵。",
    }
    res = client.post("/events", json=body, headers=API_KEY_HEADERS)
    assert res.status_code == 201
    data = res.json()
    assert data["ai_verdict"] == "true_alarm"
    assert data["ai_confidence"] == 0.92
    assert data["ai_reasoning"] == "畫面中人物平躺在地，姿態符合跌倒特徵。"
    # AI 建議不是人工判定：status 仍是 pending、人工 verdict 仍是 None，不能被 AI 建議動到
    assert data["status"] == "pending"
    assert data["verdict"] is None


def test_ai建議false_alarm_不會自動關閉事件(client):
    body = {
        **VALID_BODY,
        "ai_verdict": "false_alarm",
        "ai_confidence": 0.8,
        "ai_reasoning": "根據影像，現場沒有任何人存在，因此可以確定並非真實的跌倒事件。",
    }
    res = client.post("/events", json=body, headers=API_KEY_HEADERS)
    assert res.status_code == 201
    data = res.json()
    assert data["ai_verdict"] == "false_alarm"
    # 護欄：AI 判斷 false_alarm 只是建議，事件仍是 pending、等人工按確認，不能被自動結案
    assert data["status"] == "pending"
    assert data["verdict"] is None
    assert data["resolved_by"] is None

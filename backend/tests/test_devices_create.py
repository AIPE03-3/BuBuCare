# test_devices_create.py
# 測試 POST /devices：admin 新增鏡頭（接真實 RTSP 攝影機的註冊入口）

from core.models import Device


def _admin_headers(client):
    login = client.post("/login", data={"username": "boss", "password": "adminpass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_admin_creates_device_with_stream_channel(client, db_session):
    # admin 新增一台指定房號的攝影機 → 201，回應是完整的裝置結構、DB 也存進去了
    res = client.post("/devices", headers=_admin_headers(client), json={
        "device_id": 301,
        "device_name": "寢室-301",
        "stream_channel": "cam301",
        "stream_channel_detect": "cam301_out",
        "location_id": 1,
    })
    assert res.status_code == 201
    assert res.json() == {
        "device_id": 301,
        "device_name": "寢室-301",
        "location": "交誼廳",   # location_id=1 的區域名，JOIN 好夾帶
        "floor": None,
        "stream_channel": "cam301",
        "stream_channel_detect": "cam301_out",
        # conftest 的 isolate_mediamtx_base_url 把 MEDIAMTX_BASE_URL 釘成空字串
        # → 兩條 WHEP 網址都組不出來，回 None（不管本機 .env 有沒有設）
        "stream_url": None,
        "stream_url_detect": None,
        "status": "active",     # 沒給 status → 預設 active
    }

    db_session.expire_all()
    device = db_session.query(Device).filter(Device.device_id == 301).first()
    # 存進 DB 的是頻道名，不是完整網址（主機位址由各消費端自己接）
    assert device.stream_channel == "cam301"
    assert device.stream_channel_detect == "cam301_out"
    assert device.company_id == 1  # 前端不用給，後端固定填 1


def test_create_minimal_body_uses_defaults(client):
    # 只給必填的 device_name：status 預設 active、其餘留空、device_id 由資料庫自動編
    res = client.post("/devices", headers=_admin_headers(client),
                      json={"device_name": "新鏡頭"})
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "active"
    assert body["stream_channel"] is None
    assert body["stream_channel_detect"] is None
    assert body["stream_url"] is None
    assert body["location"] is None
    assert body["device_id"] != 1  # 不會撞掉種子裝置 1


def test_created_device_appears_in_list(client, auth_headers):
    # AI 端實際走的路徑：新增完之後 GET /devices 要看得到，且 stream_channel 一字不差
    #（AI 端拿這個頻道名自組 rtsp://<MEDIAMTX_HOST>:8554/<頻道名>）
    channel = "phone_a"
    created = client.post("/devices", headers=_admin_headers(client), json={
        "device_id": 302, "device_name": "寢室-302", "stream_channel": channel,
    })
    assert created.status_code == 201

    listed = client.get("/devices", headers=auth_headers)
    assert listed.status_code == 200
    device = next(d for d in listed.json() if d["device_id"] == 302)
    assert device["stream_channel"] == channel


def test_duplicate_device_id_returns_400(client):
    # 種子裝置 1 已存在，撞號要明確擋下（不是 500）
    res = client.post("/devices", headers=_admin_headers(client),
                      json={"device_id": 1, "device_name": "撞號"})
    assert res.status_code == 400


def test_unknown_location_id_returns_400(client):
    res = client.post("/devices", headers=_admin_headers(client),
                      json={"device_name": "掛到不存在的區域", "location_id": 999})
    assert res.status_code == 400


def test_empty_device_name_returns_422(client):
    res = client.post("/devices", headers=_admin_headers(client),
                      json={"device_name": ""})
    assert res.status_code == 422


def test_invalid_status_returns_422(client):
    res = client.post("/devices", headers=_admin_headers(client),
                      json={"device_name": "狀態亂填", "status": "broken"})
    assert res.status_code == 422


def test_too_long_stream_channel_returns_422(client):
    # DB 欄位是 String(255)，超長要在 pydantic 就擋下，不要掉到資料庫變 500
    res = client.post("/devices", headers=_admin_headers(client),
                      json={"device_name": "超長頻道名", "stream_channel": "a" * 300})
    assert res.status_code == 422


def test_staff_cannot_create_returns_403(client, auth_headers):
    # auth_headers 是 staff（alice）的 token
    res = client.post("/devices", headers=auth_headers, json={"device_name": "偷加"})
    assert res.status_code == 403


def test_create_requires_login(client):
    res = client.post("/devices", json={"device_name": "沒登入"})
    assert res.status_code == 401

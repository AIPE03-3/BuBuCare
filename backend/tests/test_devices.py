# test_devices.py
# 測試 GET /devices：鏡頭清單（JOIN locations 夾帶位置資訊）

from core.models import Device, Location


def test_get_devices_returns_seed_device(client, auth_headers):
    # 登入後查清單 → 200，種子裝置的欄位形狀正確
    res = client.get("/devices", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    first = data[0]
    assert first == {
        "device_id": 1,
        "device_name": "交誼廳-01",
        "location": "交誼廳",
        "floor": None,          # 種子 Location 沒設樓層
        "stream_channel": None,        # 種子未填頻道名
        "stream_channel_detect": None,
        "stream_url": None,            # 沒頻道名、測試環境也沒設 MEDIAMTX_BASE_URL → 組不出網址
        "stream_url_detect": None,
        "status": "active",
    }


def test_get_devices_includes_floor(client, auth_headers, db_session):
    # 位置有設樓層時，floor 帶出字串
    db_session.add(Location(location_id=2, location_name="復健室", floor="2F", company_id=1))
    db_session.add(Device(device_id=2, device_name="復健室-01", location_id=2,
                          status="active", company_id=1))
    db_session.commit()

    res = client.get("/devices", headers=auth_headers)
    target = next(d for d in res.json() if d["device_id"] == 2)
    assert target["location"] == "復健室"
    assert target["floor"] == "2F"


def test_get_devices_without_location_returns_null(client, auth_headers, db_session):
    # 裝置沒設位置（location_id 為 NULL）→ location / floor 都回 null
    db_session.add(Device(device_id=3, device_name="倉庫-01",
                          status="active", company_id=1))
    db_session.commit()

    res = client.get("/devices", headers=auth_headers)
    target = next(d for d in res.json() if d["device_id"] == 3)
    assert target["location"] is None
    assert target["floor"] is None


def test_get_devices_requires_login(client):
    # 沒帶 token → 401
    res = client.get("/devices")
    assert res.status_code == 401

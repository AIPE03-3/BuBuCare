# test_devices_rename.py
# 測試 PATCH /devices/{device_id}：admin 改鏡頭名稱

from backend.core.models import Device


def _admin_token(client):
    login = client.post("/login", data={"username": "boss", "password": "adminpass"})
    return login.json()["access_token"]


def test_admin_renames_device(client, db_session):
    # admin 改名 → 200，回應與 DB 都是新名字
    token = _admin_token(client)
    res = client.patch("/devices/1", json={"device_name": "交誼廳-东侧"},
                       headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["device_name"] == "交誼廳-东侧"
    assert res.json()["location"] == "交誼廳"  # 其他欄位照常帶出

    db_session.expire_all()
    device = db_session.query(Device).filter(Device.device_id == 1).first()
    assert device.device_name == "交誼廳-东侧"


def test_rename_unknown_device_returns_404(client):
    token = _admin_token(client)
    res = client.patch("/devices/999", json={"device_name": "幽靈鏡頭"},
                       headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 404


def test_staff_cannot_rename_returns_403(client, auth_headers):
    # auth_headers 是 staff（alice）的 token
    res = client.patch("/devices/1", json={"device_name": "偷改"}, headers=auth_headers)
    assert res.status_code == 403


def test_empty_name_returns_422(client):
    token = _admin_token(client)
    res = client.patch("/devices/1", json={"device_name": ""},
                       headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 422


def test_rename_requires_login(client):
    res = client.patch("/devices/1", json={"device_name": "沒登入"})
    assert res.status_code == 401

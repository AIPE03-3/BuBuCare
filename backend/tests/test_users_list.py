# test_users_list.py
# 測試 GET /users：admin 查使用者名單（只回未停用帳號、永不回傳 password）

from core.models import User


def _admin_token(client):
    login = client.post("/login", data={"username": "boss", "password": "adminpass"})
    return login.json()["access_token"]


def test_admin_lists_active_users(client):
    # admin 查名單 → 200，含種子兩帳號，欄位形狀正確
    token = _admin_token(client)
    res = client.get("/users", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    by_employee_id = {u["employee_id"]: u for u in data}
    assert set(by_employee_id.keys()) == {"alice", "boss"}
    alice = by_employee_id["alice"]
    assert set(alice.keys()) == {"id", "employee_id", "full_name", "role"}  # 白名單四欄
    assert alice["full_name"] == "愛麗絲"
    assert alice["role"] == "staff"


def test_deactivated_user_not_listed(client, db_session):
    # 停用的帳號不出現在名單
    alice = db_session.query(User).filter(User.employee_id == "alice").first()
    alice.is_active = False
    db_session.commit()

    token = _admin_token(client)
    res = client.get("/users", headers={"Authorization": f"Bearer {token}"})
    ids = [u["employee_id"] for u in res.json()]
    assert "alice" not in ids
    assert "boss" in ids


def test_response_never_contains_password(client):
    # 任何一筆都不能出現 password 欄位（連雜湊值也不行）
    token = _admin_token(client)
    res = client.get("/users", headers={"Authorization": f"Bearer {token}"})
    for user in res.json():
        assert "password" not in user


def test_staff_cannot_list_users_returns_403(client, auth_headers):
    res = client.get("/users", headers=auth_headers)
    assert res.status_code == 403


def test_list_users_requires_login(client):
    res = client.get("/users")
    assert res.status_code == 401

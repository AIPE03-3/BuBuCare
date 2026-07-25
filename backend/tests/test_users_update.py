# test_users_update.py
# 測試 PATCH /users/{user_id}：admin 改使用者姓名（只收 full_name）
# 密碼不從這支走：重設密碼已有專屬端點 /users/{id}/password（含 must_change_password 行為）

from core.models import User


def _admin_token(client):
    login = client.post("/login", data={"username": "boss", "password": "adminpass"})
    return login.json()["access_token"]


def test_admin_updates_full_name(client, db_session):
    alice = db_session.query(User).filter(User.employee_id == "alice").first()
    token = _admin_token(client)
    res = client.patch(f"/users/{alice.id}", json={"full_name": "愛麗絲·王"},
                       headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json() == {"id": alice.id, "employee_id": "alice",
                          "full_name": "愛麗絲·王", "role": "staff"}

    db_session.expire_all()
    after = db_session.query(User).filter(User.employee_id == "alice").first()
    assert after.full_name == "愛麗絲·王"


def test_update_unknown_user_returns_404(client):
    token = _admin_token(client)
    res = client.patch("/users/999", json={"full_name": "查無此人"},
                       headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 404


def test_role_field_is_ignored(client, db_session):
    # 就算多塞 role 欄位也不會被改：防權限竄改（Pydantic 模型只收 full_name）
    alice = db_session.query(User).filter(User.employee_id == "alice").first()
    token = _admin_token(client)
    res = client.patch(f"/users/{alice.id}",
                       json={"full_name": "愛麗絲", "role": "admin"},
                       headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200

    db_session.expire_all()
    after = db_session.query(User).filter(User.employee_id == "alice").first()
    assert after.role == "staff"  # role 沒被動


def test_empty_full_name_returns_422(client, db_session):
    alice = db_session.query(User).filter(User.employee_id == "alice").first()
    token = _admin_token(client)
    res = client.patch(f"/users/{alice.id}", json={"full_name": ""},
                       headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 422


def test_staff_cannot_update_returns_403(client, auth_headers, db_session):
    alice = db_session.query(User).filter(User.employee_id == "alice").first()
    res = client.patch(f"/users/{alice.id}", json={"full_name": "偷改"}, headers=auth_headers)
    assert res.status_code == 403

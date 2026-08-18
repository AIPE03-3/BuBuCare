# test_reset_password.py
# 測試 PATCH /users/{id}/password（admin 幫別人重設密碼）
# 共用設定（資料庫、測試帳號）都在 conftest.py，pytest 會自動載入

from core.models import User


def _admin_headers(client):
    login = client.post("/login", data={"username": "boss", "password": "adminpass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _alice_id(db_session):
    return db_session.query(User).filter(User.employee_id == "alice").first().id


def test_admin_reset_password_success_and_flag_set_true(client, db_session):
    # admin 重設成功 → 200；alice 用新臨時密碼登入，會被要求改密碼
    res = client.patch(f"/users/{_alice_id(db_session)}/password",
                       json={"new_password": "temp99"}, headers=_admin_headers(client))
    assert res.status_code == 200

    relogin = client.post("/login", data={"username": "alice", "password": "temp99"})
    assert relogin.status_code == 200
    assert relogin.json()["must_change_password"] is True


def test_staff_cannot_reset_password_returns_403(client, db_session):
    login = client.post("/login", data={"username": "alice", "password": "secret123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    res = client.patch(f"/users/{_alice_id(db_session)}/password",
                       json={"new_password": "temp99"}, headers=headers)
    assert res.status_code == 403


def test_reset_password_nonexistent_user_returns_404(client):
    res = client.patch("/users/99999/password",
                       json={"new_password": "temp99"}, headers=_admin_headers(client))
    assert res.status_code == 404


def test_reset_password_too_short_returns_422(client, db_session):
    res = client.patch(f"/users/{_alice_id(db_session)}/password",
                       json={"new_password": "12345"}, headers=_admin_headers(client))
    assert res.status_code == 422

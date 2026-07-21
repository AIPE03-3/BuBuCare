# test_change_password.py
# 測試 PATCH /me/password（登入者改自己的密碼）
# 共用設定（資料庫、測試帳號）都在 conftest.py，pytest 會自動載入

from backend.core.models import User


def test_change_password_success_and_flag_reset(client, db_session):
    # 改密碼成功 → 200；新密碼能登入；must_change_password 歸 False
    res = client.patch("/me/password",
                       json={"old_password": "secret123", "new_password": "newpw66"},
                       headers=_alice_headers(client))
    assert res.status_code == 200

    relogin = client.post("/login", data={"username": "alice", "password": "newpw66"})
    assert relogin.status_code == 200
    assert relogin.json()["must_change_password"] is False


def test_change_password_wrong_old_password_returns_400(client):
    # 舊密碼錯 → 400（不是 401：401 會被前端當 token 失效踢回登入頁）
    res = client.patch("/me/password",
                       json={"old_password": "wrongpass", "new_password": "newpw66"},
                       headers=_alice_headers(client))
    assert res.status_code == 400
    # 密碼沒被改掉：原密碼仍能登入
    relogin = client.post("/login", data={"username": "alice", "password": "secret123"})
    assert relogin.status_code == 200


def test_change_password_too_short_returns_422(client):
    # 新密碼低於 6 碼 → Pydantic 擋下 422
    res = client.patch("/me/password",
                       json={"old_password": "secret123", "new_password": "12345"},
                       headers=_alice_headers(client))
    assert res.status_code == 422


def test_change_password_without_token_returns_401(client):
    res = client.patch("/me/password",
                       json={"old_password": "secret123", "new_password": "newpw66"})
    assert res.status_code == 401


def _alice_headers(client):
    login = client.post("/login", data={"username": "alice", "password": "secret123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}

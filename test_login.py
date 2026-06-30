# test_login.py
# 測試 POST /login 路由的所有情況
# 共用設定（資料庫、測試帳號）都在 conftest.py，pytest 會自動載入

from auth import decode_access_token


def test_login_correct_credentials_returns_token(client):
    # 正確帳號密碼 → 應該回傳 200 和 access_token
    response = client.post("/login", data={"username": "alice", "password": "secret123"})
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


def test_login_wrong_password_returns_401(client):
    # 密碼錯誤 → 應該回傳 401
    response = client.post("/login", data={"username": "alice", "password": "wrongpass"})
    assert response.status_code == 401


def test_login_nonexistent_user_returns_401(client):
    # 帳號不存在 → 應該回傳 401
    response = client.post("/login", data={"username": "nobody", "password": "secret123"})
    assert response.status_code == 401


def test_login_token_contains_correct_username_and_role(client):
    # 登入後拿到的 token，解碼後應該包含正確的 username 和 role
    response = client.post("/login", data={"username": "alice", "password": "secret123"})
    token = response.json()["access_token"]
    payload = decode_access_token(token)
    assert payload["sub"] == "alice"
    assert payload["role"] == "staff"


def test_login_admin_token_contains_admin_role(client):
    # admin 登入後，token 裡的 role 應該是 "admin"
    response = client.post("/login", data={"username": "boss", "password": "adminpass"})
    token = response.json()["access_token"]
    payload = decode_access_token(token)
    assert payload["sub"] == "boss"
    assert payload["role"] == "admin"

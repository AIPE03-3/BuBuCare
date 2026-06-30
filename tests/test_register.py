# test_register.py
# 測試 POST /register 路由的所有情況
# 共用設定（資料庫、測試帳號）都在 conftest.py，pytest 會自動載入

from auth import decode_access_token


def test_register_new_user_returns_success_message(client):
    # 用一個全新的帳號名稱註冊 → 應該成功，回傳的訊息裡包含帳號名
    response = client.post("/register", json={"username": "newuser", "password": "pass123"})
    assert response.status_code == 200
    assert "newuser" in response.json()["message"]


def test_register_duplicate_username_returns_400(client):
    # alice 已經在 conftest.py 裡建好了，再次註冊同名帳號 → 應該回傳 400
    response = client.post("/register", json={"username": "alice", "password": "anything"})
    assert response.status_code == 400


def test_register_new_user_default_role_is_staff(client):
    # 新註冊的帳號沒有指定角色，預設應該是 staff
    # 做法：先註冊，再登入，解碼 token 確認 role
    client.post("/register", json={"username": "newstaff", "password": "pass123"})
    login = client.post("/login", data={"username": "newstaff", "password": "pass123"})
    token = login.json()["access_token"]
    payload = decode_access_token(token)
    assert payload["role"] == "staff"

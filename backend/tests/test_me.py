# test_me.py
# 測試 GET /me 路由的所有情況
# 共用設定（資料庫、測試帳號）都在 conftest.py，pytest 會自動載入


def test_me_returns_username_and_role(client):
    # 帶著合法 token → 應該回傳自己的帳號名稱和角色
    login = client.post("/login", data={"username": "alice", "password": "secret123"})
    token = login.json()["access_token"]
    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"username": "alice", "role": "staff"}


def test_me_without_token_returns_401(client):
    # 沒有帶 token → 應該回傳 401
    response = client.get("/me")
    assert response.status_code == 401


def test_me_with_invalid_token_returns_401(client):
    # 帶假的 token → 應該回傳 401
    response = client.get("/me", headers={"Authorization": "Bearer this.is.garbage"})
    assert response.status_code == 401

# test_admin.py
# 測試 DELETE /users/{id} 路由的所有情況
# 這個路由只有 admin 角色才能使用
# 共用設定（資料庫、測試帳號）都在 conftest.py，pytest 會自動載入

from backend.core.models import User


def _admin_token(client):
    # 幫 boss（admin）登入，回傳 token，讓下面的測試重複使用
    login = client.post("/login", data={"username": "boss", "password": "adminpass"})
    return login.json()["access_token"]


def _staff_token(client):
    # 幫 alice（staff）登入，回傳 token，讓下面的測試重複使用
    login = client.post("/login", data={"username": "alice", "password": "secret123"})
    return login.json()["access_token"]


def test_admin_can_delete_existing_user(client, db_session):
    # admin 刪除存在的使用者 → 應該回傳 200
    alice = db_session.query(User).filter(User.name == "alice").first()
    token = _admin_token(client)
    response = client.delete(f"/users/{alice.id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_staff_cannot_delete_user_returns_403(client, db_session):
    # staff 嘗試刪人 → 沒有權限，應該回傳 403
    alice = db_session.query(User).filter(User.name == "alice").first()
    token = _staff_token(client)
    response = client.delete(f"/users/{alice.id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_delete_nonexistent_user_returns_404(client):
    # 刪一個不存在的 ID → 應該回傳 404
    token = _admin_token(client)
    response = client.delete("/users/99999", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404


def test_delete_without_token_returns_401(client, db_session):
    # 沒有帶 token 就刪 → 應該回傳 401
    alice = db_session.query(User).filter(User.name == "alice").first()
    response = client.delete(f"/users/{alice.id}")
    assert response.status_code == 401

# test_admin.py
# 測試 DELETE /users/{id} 路由的所有情況
# 這個路由只有 admin 角色才能使用
# 共用設定（資料庫、測試帳號）都在 conftest.py，pytest 會自動載入

from core.models import User


def _admin_token(client):
    # 幫 boss（admin）登入，回傳 token，讓下面的測試重複使用
    login = client.post("/login", data={"username": "boss", "password": "adminpass"})
    return login.json()["access_token"]


def _staff_token(client):
    # 幫 alice（staff）登入，回傳 token，讓下面的測試重複使用
    login = client.post("/login", data={"username": "alice", "password": "secret123"})
    return login.json()["access_token"]


def test_admin_delete_soft_deletes_user(client, db_session):
    # admin 停用使用者 → 200；資料還在、is_active 變 False；本人登不進來
    alice = db_session.query(User).filter(User.employee_id == "alice").first()
    token = _admin_token(client)
    response = client.delete(f"/users/{alice.id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200

    db_session.expire_all()  # 清掉 session 快取，強制重新從 DB 讀最新值
    after = db_session.query(User).filter(User.employee_id == "alice").first()
    assert after is not None            # 軟刪除：資料沒有真的消失
    assert after.is_active is False

    relogin = client.post("/login", data={"username": "alice", "password": "secret123"})
    assert relogin.status_code == 401   # 停用後登不進來


def test_staff_cannot_delete_user_returns_403(client, db_session):
    # staff 嘗試刪人 → 沒有權限，應該回傳 403
    alice = db_session.query(User).filter(User.employee_id == "alice").first()
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
    alice = db_session.query(User).filter(User.employee_id == "alice").first()
    response = client.delete(f"/users/{alice.id}")
    assert response.status_code == 401


def test_admin_cannot_delete_self_returns_400(client, db_session):
    # admin 停用自己 → 400（防止最後一個 admin 把自己鎖死）
    boss = db_session.query(User).filter(User.employee_id == "boss").first()
    token = _admin_token(client)
    response = client.delete(f"/users/{boss.id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 400

    db_session.expire_all()
    assert db_session.query(User).filter(
        User.employee_id == "boss").first().is_active is True

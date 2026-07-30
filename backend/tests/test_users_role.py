# test_users_role.py
# 測試 PATCH /users/{user_id}/role：admin 改別人的角色（只收 role）
# 改名字走 /users/{id}、改密碼走 /users/{id}/password，一件事一個入口

from core.models import User


def _admin_token(client):
    login = client.post("/login", data={"username": "boss", "password": "adminpass"})
    return login.json()["access_token"]


def _get_user(db_session, employee_id):
    db_session.expire_all()  # 清掉 session 快取，才讀得到 API 那邊剛 commit 的值
    return db_session.query(User).filter(User.employee_id == employee_id).first()


def test_admin_promotes_staff_to_admin(client, db_session):
    alice = _get_user(db_session, "alice")
    token = _admin_token(client)
    res = client.patch(f"/users/{alice.id}/role", json={"role": "admin"},
                       headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json() == {"id": alice.id, "employee_id": "alice",
                          "full_name": "愛麗絲", "role": "admin"}

    assert _get_user(db_session, "alice").role == "admin"


def test_admin_demotes_admin_to_staff(client, db_session):
    # 先把 alice 升成 admin，再由 boss 把她降回 staff（降級跟升級是兩條不同的路要各測一次）
    alice = _get_user(db_session, "alice")
    alice.role = "admin"
    db_session.commit()

    token = _admin_token(client)
    res = client.patch(f"/users/{alice.id}/role", json={"role": "staff"},
                       headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["role"] == "staff"

    assert _get_user(db_session, "alice").role == "staff"


def test_admin_cannot_change_own_role(client, db_session):
    # 防最後一個 admin 把自己降成 staff 後沒人能開帳號（同 DELETE /users/{id} 的「不能停用自己」）
    boss = _get_user(db_session, "boss")
    token = _admin_token(client)
    res = client.patch(f"/users/{boss.id}/role", json={"role": "staff"},
                       headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 400

    assert _get_user(db_session, "boss").role == "admin"  # 沒被改到


def test_unknown_user_returns_404(client):
    token = _admin_token(client)
    res = client.patch("/users/999/role", json={"role": "admin"},
                       headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 404
    # 連 detail 一起驗：路由不存在時 FastAPI 也回 404（detail 是 "Not Found"），
    # 只看狀態碼的話，端點還沒寫就會假綠燈
    assert res.json()["detail"] == "找不到使用者"


def test_staff_cannot_change_role_returns_403(client, auth_headers, db_session):
    alice = _get_user(db_session, "alice")
    res = client.patch(f"/users/{alice.id}/role", json={"role": "admin"},
                       headers=auth_headers)
    assert res.status_code == 403

    assert _get_user(db_session, "alice").role == "staff"


def test_invalid_role_value_returns_422(client, db_session):
    alice = _get_user(db_session, "alice")
    token = _admin_token(client)
    res = client.patch(f"/users/{alice.id}/role", json={"role": "superuser"},
                       headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 422


def test_old_token_keeps_old_role_until_relogin(client, auth_headers, db_session):
    # 刻意的設計，不是 bug：角色寫在 JWT 裡，權限檢查讀 token 不查資料庫
    # （core/dependencies.py 的 require_admin），所以改完角色要重新登入才生效。
    # 這支測試把這個契約釘住——哪天有人把 get_current_user 改成查資料庫，這裡會紅燈。
    alice = _get_user(db_session, "alice")   # auth_headers 裡的 token 是升級「之前」拿的
    token = _admin_token(client)
    promote = client.patch(f"/users/{alice.id}/role", json={"role": "admin"},
                           headers={"Authorization": f"Bearer {token}"})
    assert promote.status_code == 200        # 升級真的成功了，下面的斷言才有意義

    res = client.get("/me", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["role"] == "staff"     # 舊 token 仍是舊角色

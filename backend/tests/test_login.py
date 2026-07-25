# test_login.py
# 測試 POST /login 路由的所有情況
# 共用設定（資料庫、測試帳號）都在 conftest.py，pytest 會自動載入

from core.auth import decode_access_token
from core.models import User
from core.security import hash_password


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


def test_login_token_contains_employee_id_fullname_and_role(client):
    # 登入後拿到的 token，解碼後應包含員編（sub）、姓名、角色
    response = client.post("/login", data={"username": "alice", "password": "secret123"})
    token = response.json()["access_token"]
    payload = decode_access_token(token)
    assert payload["sub"] == "alice"
    assert payload["full_name"] == "愛麗絲"
    assert payload["role"] == "staff"


def test_login_admin_token_contains_admin_role(client):
    # admin 登入後，token 裡的 role 應該是 "admin"
    response = client.post("/login", data={"username": "boss", "password": "adminpass"})
    token = response.json()["access_token"]
    payload = decode_access_token(token)
    assert payload["sub"] == "boss"
    assert payload["role"] == "admin"


def test_login_updates_last_login_time(client, db_session):
    # 登入前 alice 沒有登入紀錄；登入成功後 last_login_time 應該被填上
    before = db_session.query(User).filter(User.employee_id == "alice").first()
    assert before.last_login_time is None

    client.post("/login", data={"username": "alice", "password": "secret123"})

    db_session.expire_all()  # 清掉 session 快取，強制重新從 DB 讀最新值
    after = db_session.query(User).filter(User.employee_id == "alice").first()
    assert after.last_login_time is not None


def test_login_response_contains_must_change_password(client):
    # 種子帳號 alice 的 must_change_password 是 False，登入回應要帶出來
    response = client.post("/login", data={"username": "alice", "password": "secret123"})
    assert response.json()["must_change_password"] is False


def test_login_new_account_must_change_password_true(client, db_session):
    # 沒指定 must_change_password 的新帳號（模型預設 True）→ 登入回應是 true
    db_session.add(User(employee_id="E777", full_name="新人",
                        password=hash_password("temp66"), role="staff"))
    db_session.commit()
    response = client.post("/login", data={"username": "E777", "password": "temp66"})
    assert response.json()["must_change_password"] is True


def test_login_inactive_account_returns_401_with_same_message(client, db_session):
    # 停用帳號登入 → 401，且訊息與帳密錯誤完全相同（不透露帳號被停用）
    alice = db_session.query(User).filter(User.employee_id == "alice").first()
    alice.is_active = False
    db_session.commit()

    inactive = client.post("/login", data={"username": "alice", "password": "secret123"})
    wrong_pw = client.post("/login", data={"username": "boss", "password": "wrongpass"})
    assert inactive.status_code == 401
    assert inactive.json()["detail"] == wrong_pw.json()["detail"]

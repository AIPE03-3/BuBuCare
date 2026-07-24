# test_register.py
# 測試 POST /register（admin-only）的所有情況
# 共用設定（資料庫、測試帳號）都在 conftest.py，pytest 會自動載入

from core.models import User


def _admin_headers(client):
    login = client.post("/login", data={"username": "boss", "password": "adminpass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _staff_headers(client):
    login = client.post("/login", data={"username": "alice", "password": "secret123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _valid_body(**overrides):
    body = {"employee_id": "E100", "full_name": "新同事", "password": "temp66"}
    body.update(overrides)
    return body


def test_register_without_token_returns_401(client):
    # 註冊已不是公開端點，沒帶 token → 401
    response = client.post("/register", json=_valid_body())
    assert response.status_code == 401


def test_register_with_staff_token_returns_403(client):
    # staff 不能開帳號 → 403
    response = client.post("/register", json=_valid_body(), headers=_staff_headers(client))
    assert response.status_code == 403


def test_admin_register_returns_201_with_user_data(client):
    # admin 開帳號成功 → 201 + 新帳號基本資料
    response = client.post("/register", json=_valid_body(), headers=_admin_headers(client))
    assert response.status_code == 201
    body = response.json()
    assert body["employee_id"] == "E100"
    assert body["full_name"] == "新同事"
    assert body["role"] == "staff"
    assert isinstance(body["id"], int)


def test_new_account_defaults_must_change_password_true(client, db_session):
    # admin 開的新帳號預設要求首次登入改密碼
    client.post("/register", json=_valid_body(), headers=_admin_headers(client))
    user = db_session.query(User).filter(User.employee_id == "E100").first()
    assert user.must_change_password is True


def test_admin_can_register_admin_role(client, db_session):
    # request 帶 role=admin → 建出 admin 帳號
    client.post("/register", json=_valid_body(role="admin"), headers=_admin_headers(client))
    user = db_session.query(User).filter(User.employee_id == "E100").first()
    assert user.role == "admin"


def test_register_duplicate_employee_id_returns_400(client):
    # alice 已在 conftest 建好，同員編再開 → 400
    response = client.post("/register", json=_valid_body(employee_id="alice"),
                           headers=_admin_headers(client))
    assert response.status_code == 400


def test_register_duplicate_email_returns_400(client):
    # email 有填且撞到既有帳號 → 400（不能放給 unique 約束炸 500）
    response = client.post("/register", json=_valid_body(email="alice@test.com"),
                           headers=_admin_headers(client))
    assert response.status_code == 400


def test_register_without_email_succeeds(client):
    # email 選填，不給也能開帳號
    response = client.post("/register", json=_valid_body(), headers=_admin_headers(client))
    assert response.status_code == 201


def test_register_short_password_returns_422(client):
    # 密碼最低 6 碼，5 碼 → Pydantic 驗證擋下，422
    response = client.post("/register", json=_valid_body(password="12345"),
                           headers=_admin_headers(client))
    assert response.status_code == 422

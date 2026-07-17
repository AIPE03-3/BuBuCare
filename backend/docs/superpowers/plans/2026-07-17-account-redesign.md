# 帳號系統改版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依 `backend/docs/superpowers/specs/2026-07-17-account-redesign-design.md`，把自取帳號改成員編登入＋admin 管理帳號生命週期（開帳號／重設密碼／停用）。

**Architecture:** `user_account` 表砍掉重建（`name` 拆成 `employee_id` + `full_name`，新增 `must_change_password`／`is_active`）；`backend/users/router.py` 改寫既有 4 端點＋新增 2 端點；JWT `sub` 改放 employee_id。Task 1 先做「欄位拆分」的全面改名讓測試回綠，之後每個 Task 各加一個行為。

**Tech Stack:** FastAPI + SQLAlchemy 2.0（Mapped/mapped_column）+ Pydantic + passlib/bcrypt + pytest（in-memory SQLite）

## Global Constraints

- 測試指令（PowerShell 全新 session）：`& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest -v`（已啟動 venv 則 `uv run pytest -v`）
- bcrypt 鎖定 4.0.1，不得升級
- 固定選項欄位用原生 SQLAlchemy `Enum` + `create_constraint=True`（專案慣例）
- 密碼欄位一律 Pydantic `Field(min_length=6)`
- 錯誤訊息、docstring、註解一律繁體中文
- **commit 由使用者親自執行**：計畫裡的 Commit step ＝ 停下來提醒使用者、附建議訊息，不要代打；commit 訊息結尾不加任何模型署名
- 執行節奏（使用者偏好）：測試相關 step 可連續跑；寫正式程式檔前、每個 Task 結束後要停下來說明並等確認

## 測試種子的命名決策（Task 1 依此寫）

測試種子帳號的 `employee_id` 直接沿用舊帳號名字串 `"alice"`／`"boss"`（員編就是字串，內容不限格式）。
這讓所有 `client.post("/login", data={"username": "alice", ...})` 與 `payload["sub"] == "alice"`
的既有測試**完全不用改**，改動面集中在「查詢欄位改名」與「回傳格式」。
`full_name` 種子值：alice → `"愛麗絲"`、boss → `"老大"`。

---

### Task 1: 欄位拆分的全面改名（model → 種子 → router → 既有測試回綠）

`name` 一拆掉，所有引用它的地方同時壞，所以這個 Task 是不可再切的「改名波」：
model、conftest、init_db、router 既有 4 端點、既有測試一次跟上，結束時全套測試回綠。
本 Task **只做改名與新欄位**，不加任何新行為（admin-only、is_active 檢查等都在後面的 Task）。

**Files:**
- Modify: `backend/core/models.py`（User 類別，第 9-34 行）
- Modify: `backend/tests/conftest.py`（種子帳號，第 75-76 行）
- Modify: `backend/init_db.py`（seed_accounts，第 92-107 行）
- Modify: `backend/users/router.py`（register / login / me；delete 不動）
- Modify: `backend/tests/test_login.py`、`backend/tests/test_me.py`、`backend/tests/test_admin.py`、`backend/tests/test_register.py`
- 不動：`backend/tests/test_sse.py`（employee_id 沿用 "alice"，`sub` 斷言自然通過）

**Interfaces:**
- Produces（後續所有 Task 依賴）：
  - `User` 新欄位：`employee_id: str`（unique）、`full_name: str`、`email: str | None`、`role`（Enum staff/admin）、`must_change_password: bool`（預設 True）、`is_active: bool`（預設 True）
  - JWT payload：`{"sub": <employee_id>, "full_name": <full_name>, "role": <role>}`
  - `GET /me` 回 `{"employee_id", "full_name", "role"}`

- [ ] **Step 1: 改寫既有測試的期望（先紅）**

`backend/tests/test_login.py`——只改兩處 `User.name` 查詢與新增 payload 斷言：

```python
# 第 50、56 行的查詢改成：
before = db_session.query(User).filter(User.employee_id == "alice").first()
# ...
after = db_session.query(User).filter(User.employee_id == "alice").first()
```

`test_login_token_contains_correct_username_and_role`（第 30-36 行）改名並加 full_name 斷言：

```python
def test_login_token_contains_employee_id_fullname_and_role(client):
    # 登入後拿到的 token，解碼後應包含員編（sub）、姓名、角色
    response = client.post("/login", data={"username": "alice", "password": "secret123"})
    token = response.json()["access_token"]
    payload = decode_access_token(token)
    assert payload["sub"] == "alice"
    assert payload["full_name"] == "愛麗絲"
    assert payload["role"] == "staff"
```

`backend/tests/test_me.py` 第 6-12 行改成：

```python
def test_me_returns_employee_id_fullname_and_role(client):
    # 帶著合法 token → 應回傳員編、姓名、角色（全部來自 JWT，不查資料庫）
    login = client.post("/login", data={"username": "alice", "password": "secret123"})
    token = login.json()["access_token"]
    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"employee_id": "alice", "full_name": "愛麗絲", "role": "staff"}
```

`backend/tests/test_admin.py`——三處 `User.name` 查詢（第 23、31、46 行）改成：

```python
alice = db_session.query(User).filter(User.employee_id == "alice").first()
```

`backend/tests/test_register.py` 整檔暫換成過渡版（Task 2 會再全面重寫成 admin-only）：

```python
# test_register.py
# 過渡版：欄位改名後的最小驗證。Task 2 改 admin-only 時整檔重寫。


def test_register_new_user_returns_success_message(client):
    # 用全新員編註冊 → 成功，訊息包含員編
    response = client.post("/register", json={
        "employee_id": "E100", "full_name": "新同事", "password": "pass123"})
    assert response.status_code == 200
    assert "E100" in response.json()["message"]


def test_register_duplicate_employee_id_returns_400(client):
    # alice 已在 conftest 建好，再用同員編註冊 → 400
    response = client.post("/register", json={
        "employee_id": "alice", "full_name": "冒牌貨", "password": "anything"})
    assert response.status_code == 400


def test_register_without_email_succeeds(client):
    # email 改成選填，不給也能註冊成功
    response = client.post("/register", json={
        "employee_id": "E101", "full_name": "沒信箱", "password": "pass123"})
    assert response.status_code == 200
```

- [ ] **Step 2: 跑測試確認紅**

Run: `uv run pytest -v`
Expected: test_login／test_me／test_admin／test_register 大量 FAIL（`User` 還沒有 `employee_id` 欄位）

- [ ] **Step 3: 改寫 `backend/core/models.py` 的 User 類別**（寫正式檔前先停下來跟使用者確認）

匯入行（第 5 行）加 `Boolean`：

```python
from sqlalchemy import Integer, String, DateTime, Float, Text, ForeignKey, Enum, Boolean
```

User 類別（第 9-34 行）整段換成：

```python
class User(Base):  # 對應資料庫裡的 user_account 表
    __tablename__ = "user_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 登入用的員工編號（機構既有人資編號），取代原本使用者自取的 name
    employee_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    # 真實姓名，顯示用
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # String(255) 給密碼雜湊值足夠空間（bcrypt 結果大約 60 字元）
    password: Mapped[str] = mapped_column(String(255), nullable=False)

    # 不再是找回密碼的管道，改選填；有填仍不可重複
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)

    # 固定選項欄位比照 status/verdict/severity 慣例：
    # PostgreSQL 真 ENUM、SQLite 用 CHECK 約束擋非法值
    role: Mapped[str] = mapped_column(
        Enum("staff", "admin", name="user_role", create_constraint=True),
        default="staff", nullable=False,
    )

    # admin 開的新帳號預設要求首次登入改密碼；種子帳號由種子腳本設 False
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # 軟刪除：停用帳號設 False，不真的刪資料（員編不可重用，資料留著可回溯）
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # 可以是空的（新帳號還沒登入過）
    last_login_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 所屬機構。default=1 表示新帳號自動掛預設公司，多租戶邏輯未來才做
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.company_id"), nullable=False, default=1
    )
```

- [ ] **Step 4: 更新 `backend/tests/conftest.py` 種子帳號**（第 75-76 行換成）

```python
    # 種子帳號的 employee_id 沿用舊名字串，讓既有登入呼叫與 sub 斷言不用改
    # must_change_password=False：種子帳號不強制改密碼，登入相關測試不受干擾
    db.add(User(employee_id="alice", full_name="愛麗絲", password=hash_password("secret123"),
                email="alice@test.com", role="staff", must_change_password=False))
    db.add(User(employee_id="boss", full_name="老大", password=hash_password("adminpass"),
                email="boss@test.com", role="admin", must_change_password=False))
```

- [ ] **Step 5: 更新 `backend/init_db.py` 的 seed_accounts**（第 92-107 行整段換成）

```python
def seed_accounts(db):
    """建立可以登入中控站的初始帳號（admin / staff01，密碼皆 123456）。

    密碼一定要經過 bcrypt 雜湊才能存，所以不能直接用 SQL INSERT 明文。
    種子帳號手動設 must_change_password=False，登入時不會被要求改密碼。
    """
    accounts = [
        {"employee_id": "admin", "full_name": "系統管理員",
         "email": "admin@fulilian.com", "role": "admin"},
        {"employee_id": "staff01", "full_name": "示範員工",
         "email": "staff01@fulilian.com", "role": "staff"},
    ]
    for account in accounts:
        if db.query(User).filter(User.employee_id == account["employee_id"]).first():
            print(f"帳號 {account['employee_id']} 已存在，略過建立")
        else:
            db.add(User(**account, password=hash_password("123456"),
                        must_change_password=False))
            db.commit()
            print(f"帳號建立完成：{account['employee_id']} / 123456（role: {account['role']}）")
```

- [ ] **Step 6: 改寫 `backend/users/router.py` 的 register／login／me**

RegisterRequest（第 25-28 行）換成（過渡版，Task 2 再加 admin-only／role／201）：

```python
class RegisterRequest(BaseModel):
    employee_id: str
    full_name: str
    password: str
    email: str | None = None  # 改選填：不再是找回密碼的管道
```

register 函式本體（第 34-52 行）換成：

```python
@router.post("/register")
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    # 查資料庫有沒有同員編的帳號
    existing = db.query(User).filter(User.employee_id == body.employee_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="員編已存在")

    new_user = User(
        employee_id=body.employee_id,
        full_name=body.full_name,
        password=hash_password(body.password),  # 密碼雜湊後才存，不存明文
        email=body.email,
        role="staff"
    )
    db.add(new_user)
    db.commit()
    return {"message": f"帳號 {body.employee_id} 建立成功"}
```

login 函式裡兩處（第 63 行查詢、第 75 行 token）改成：

```python
    user = db.query(User).filter(User.employee_id == form_data.username).first()
```

```python
    access_token = create_access_token(
        data={"sub": user.employee_id, "full_name": user.full_name, "role": user.role})
```

read_me（第 84-92 行）的回傳改成：

```python
@router.get("/me")
def read_me(current_user: dict = Depends(get_current_user)):
    # current_user 是解出來的 JWT payload，三個欄位都在裡面，不用查資料庫
    return {
        "employee_id": current_user["sub"],
        "full_name": current_user["full_name"],
        "role": current_user["role"],
    }
```

- [ ] **Step 7: 跑全套測試確認綠**

Run: `uv run pytest -v`
Expected: 全部 PASS（含 test_sse、test_events 系列——它們只透過 alice 登入拿 token，不受影響）

- [ ] **Step 8: 提醒使用者 commit**

建議訊息：`refactor: user_account 改員編登入 schema（name 拆成 employee_id + full_name）`

---

### Task 2: `POST /register` 改 admin-only（403／401／201／重複 400／min_length）

**Files:**
- Modify: `backend/users/router.py`（RegisterRequest 與 register 函式）
- Rewrite: `backend/tests/test_register.py`（整檔重寫，取代 Task 1 過渡版）

**Interfaces:**
- Consumes: Task 1 的 `User` 新欄位；既有 `require_admin`（`backend/core/dependencies.py`）
- Produces: `POST /register` 成功回 201 + `{"id", "employee_id", "full_name", "role"}`（Task 5 測試會用它開帳號的替代品——直接 db insert——所以無硬相依）

- [ ] **Step 1: 整檔重寫 `backend/tests/test_register.py`（先紅）**

```python
# test_register.py
# 測試 POST /register（admin-only）的所有情況
# 共用設定（資料庫、測試帳號）都在 conftest.py，pytest 會自動載入

from backend.core.models import User


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
```

- [ ] **Step 2: 跑測試確認紅**

Run: `uv run pytest backend/tests/test_register.py -v`
Expected: FAIL（無 token 回 200 而非 401、成功回 200 而非 201 等）

- [ ] **Step 3: 改寫 router 的 RegisterRequest 與 register**（寫正式檔前先停下來跟使用者確認）

`backend/users/router.py` 開頭 import 補（`typing` 與 pydantic）：

```python
from typing import Literal

from pydantic import BaseModel, Field
```

RegisterRequest 與 register 整段換成：

```python
class RegisterRequest(BaseModel):
    employee_id: str
    full_name: str
    password: str = Field(min_length=6)   # admin 給的臨時密碼，最低 6 碼
    role: Literal["staff", "admin"] = "staff"  # 只收這兩種值，其他直接 422
    email: str | None = None              # 改選填：不再是找回密碼的管道


# ════════════════════════════════════════════════════════
# 路由一：POST /register（admin-only：員編是人資編號，只有 admin 能開帳號）
# ════════════════════════════════════════════════════════
@router.post("/register", status_code=201)
def register(body: RegisterRequest,
             current_user: dict = Depends(require_admin),
             db: Session = Depends(get_db)):
    if db.query(User).filter(User.employee_id == body.employee_id).first():
        raise HTTPException(status_code=400, detail="員編已存在")
    # email 沒填（None）不查重——資料庫允許多筆 NULL；有填才需要擋重複
    if body.email and db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=400, detail="email 已被使用")

    new_user = User(
        employee_id=body.employee_id,
        full_name=body.full_name,
        password=hash_password(body.password),  # 密碼雜湊後才存，不存明文
        email=body.email,
        role=body.role,
        # must_change_password 不用指定：模型預設 True，逼新帳號首次登入改密碼
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)  # 讓資料庫回填自動編號的 id
    return {"id": new_user.id, "employee_id": new_user.employee_id,
            "full_name": new_user.full_name, "role": new_user.role}
```

- [ ] **Step 4: 跑全套測試確認綠**

Run: `uv run pytest -v`
Expected: 全部 PASS

- [ ] **Step 5: 提醒使用者 commit**

建議訊息：`feat: POST /register 改 admin-only，回 201 與新帳號資料`

---

### Task 3: `POST /login` 擋停用帳號＋回應帶 must_change_password

**Files:**
- Modify: `backend/users/router.py`（login 函式）
- Modify: `backend/tests/test_login.py`（加 3 個測試）

**Interfaces:**
- Consumes: Task 1 的 `User.is_active`／`User.must_change_password`
- Produces: login 回應 `{"access_token", "token_type", "must_change_password"}`（Task 4、5 的測試靠它驗證 flag 變化）

- [ ] **Step 1: 在 `backend/tests/test_login.py` 檔尾加測試（先紅）**

檔頭 import 補一行：

```python
from backend.core.security import hash_password
```

檔尾加：

```python
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
```

- [ ] **Step 2: 跑測試確認紅**

Run: `uv run pytest backend/tests/test_login.py -v`
Expected: 新增 3 個 FAIL（KeyError: 'must_change_password'；停用帳號登入回 200）

- [ ] **Step 3: 改 login 函式**（寫正式檔前先停下來跟使用者確認）

驗證段（第 66-67 行附近）換成：

```python
    # 帳號不存在、已停用、或密碼比對失敗 → 一律同一句 401，不透露差別
    if not user or not user.is_active or not verify_password(form_data.password, user.password):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")
```

回傳段換成：

```python
    # must_change_password 走回應欄位、不放進 token——
    # token 產生後內容不可變，改完密碼會翻不回來（見 spec「JWT 改動」）
    return {"access_token": access_token, "token_type": "bearer",
            "must_change_password": user.must_change_password}
```

- [ ] **Step 4: 跑全套測試確認綠**

Run: `uv run pytest -v`
Expected: 全部 PASS

- [ ] **Step 5: 提醒使用者 commit**

建議訊息：`feat: login 擋停用帳號、回應帶 must_change_password`

---

### Task 4: 新增 `PATCH /me/password`（自己改自己的密碼）

**Files:**
- Modify: `backend/users/router.py`（新增 ChangePasswordRequest 與端點）
- Create: `backend/tests/test_change_password.py`

**Interfaces:**
- Consumes: Task 1 的 JWT payload（`sub`=employee_id）；Task 3 的 login 回應（驗 flag 歸 False）
- Produces: `PATCH /me/password`，body `{"old_password", "new_password"}`，成功回 200 `{"message": "密碼已更新"}`

- [ ] **Step 1: 寫 `backend/tests/test_change_password.py`（先紅）**

```python
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
```

- [ ] **Step 2: 跑測試確認紅**

Run: `uv run pytest backend/tests/test_change_password.py -v`
Expected: 全部 FAIL（404——`/me/password` 路徑還不存在）

- [ ] **Step 3: 在 router 加端點**（寫正式檔前先停下來跟使用者確認）

```python
class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6)


# ════════════════════════════════════════════════════════
# 路由五：PATCH /me/password（登入者改自己的密碼）
# ════════════════════════════════════════════════════════
@router.patch("/me/password")
def change_my_password(body: ChangePasswordRequest,
                       current_user: dict = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    # token 的 sub 就是員編，撈出本人那筆
    user = db.query(User).filter(User.employee_id == current_user["sub"]).first()
    if user is None:
        raise HTTPException(status_code=401, detail="token 無效或過期")

    # 先驗舊密碼，防止「電腦沒鎖被別人拿去改密碼」
    if not verify_password(body.old_password, user.password):
        raise HTTPException(status_code=400, detail="舊密碼錯誤")

    user.password = hash_password(body.new_password)
    user.must_change_password = False  # 已經換掉臨時密碼，解除首次登入強制改密碼
    db.commit()
    return {"message": "密碼已更新"}
```

- [ ] **Step 4: 跑全套測試確認綠**

Run: `uv run pytest -v`
Expected: 全部 PASS

- [ ] **Step 5: 提醒使用者 commit**

建議訊息：`feat: 新增 PATCH /me/password 改自己的密碼`

---

### Task 5: 新增 `PATCH /users/{id}/password`（admin 重設別人的密碼）

**Files:**
- Modify: `backend/users/router.py`（新增 ResetPasswordRequest 與端點）
- Create: `backend/tests/test_reset_password.py`

**Interfaces:**
- Consumes: 既有 `require_admin`；Task 3 的 login 回應（驗 flag 設 True）
- Produces: `PATCH /users/{user_id}/password`，body `{"new_password"}`，成功回 200

- [ ] **Step 1: 寫 `backend/tests/test_reset_password.py`（先紅）**

```python
# test_reset_password.py
# 測試 PATCH /users/{id}/password（admin 幫別人重設密碼）
# 共用設定（資料庫、測試帳號）都在 conftest.py，pytest 會自動載入

from backend.core.models import User


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
```

- [ ] **Step 2: 跑測試確認紅**

Run: `uv run pytest backend/tests/test_reset_password.py -v`
Expected: 全部 FAIL（404——`/users/{id}/password` 路徑還不存在）

- [ ] **Step 3: 在 router 加端點**（寫正式檔前先停下來跟使用者確認）

```python
class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=6)  # admin 給的新臨時密碼


# ════════════════════════════════════════════════════════
# 路由六：PATCH /users/{user_id}/password（admin 幫忘記密碼的員工重設）
# ════════════════════════════════════════════════════════
@router.patch("/users/{user_id}/password")
def reset_user_password(user_id: int, body: ResetPasswordRequest,
                        current_user: dict = Depends(require_admin),
                        db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="找不到使用者")

    user.password = hash_password(body.new_password)
    # 這是 admin 給的臨時密碼，員工下次登入要換成自己的
    # （admin 對自己的 id 呼叫也放行：無害，只是自己下次登入會被要求改密碼；
    #   正常改自己的密碼該用 PATCH /me/password）
    user.must_change_password = True
    db.commit()
    return {"message": f"已重設使用者 {user_id} 的密碼"}
```

- [ ] **Step 4: 跑全套測試確認綠**

Run: `uv run pytest -v`
Expected: 全部 PASS

- [ ] **Step 5: 提醒使用者 commit**

建議訊息：`feat: 新增 PATCH /users/{id}/password admin 重設密碼`

---

### Task 6: `DELETE /users/{id}` 改軟刪除＋不能停用自己

**Files:**
- Modify: `backend/users/router.py`（delete_user 函式）
- Modify: `backend/tests/test_admin.py`（改寫刪除成功案例＋加 2 個測試）

**Interfaces:**
- Consumes: Task 1 的 `User.is_active`；Task 3 的 login 停用檢查（驗停用後登不進）
- Produces: 無（終端行為）

- [ ] **Step 1: 改寫 `backend/tests/test_admin.py`（先紅）**

`test_admin_can_delete_existing_user`（第 21-26 行）換成：

```python
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
```

檔尾加：

```python
def test_admin_cannot_delete_self_returns_400(client, db_session):
    # admin 停用自己 → 400（防止最後一個 admin 把自己鎖死）
    boss = db_session.query(User).filter(User.employee_id == "boss").first()
    token = _admin_token(client)
    response = client.delete(f"/users/{boss.id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 400

    db_session.expire_all()
    assert db_session.query(User).filter(
        User.employee_id == "boss").first().is_active is True
```

- [ ] **Step 2: 跑測試確認紅**

Run: `uv run pytest backend/tests/test_admin.py -v`
Expected: 兩個新／改的測試 FAIL（現在是硬刪除、也沒擋自己）

- [ ] **Step 3: 改寫 delete_user**（寫正式檔前先停下來跟使用者確認）

```python
# ════════════════════════════════════════════════════════
# 路由四：DELETE /users/{user_id}（需 admin；軟刪除＝停用，不真的刪資料）
# ════════════════════════════════════════════════════════
@router.delete("/users/{user_id}")
def delete_user(user_id: int, current_user: dict = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="找不到使用者")

    # 不能停用自己：防止最後一個 admin 把自己鎖死後沒人能開帳號
    if user.employee_id == current_user["sub"]:
        raise HTTPException(status_code=400, detail="不能停用自己的帳號")

    user.is_active = False  # 軟刪除：資料留著可回溯，員編也不會被重用
    db.commit()
    return {"message": f"已停用使用者 {user_id}"}
```

- [ ] **Step 4: 跑全套測試確認綠**

Run: `uv run pytest -v`
Expected: 全部 PASS

- [ ] **Step 5: 提醒使用者 commit**

建議訊息：`feat: DELETE /users/{id} 改軟刪除，並擋 admin 停用自己`

---

### Task 7: 收尾——正式 DB 重建、CLAUDE.md 同步、通知前端、煙霧測試

**Files:**
- Modify: `CLAUDE.md`（API 路由表、資料庫段落）
- 手動操作: AWS RDS 的 `user_account` 砍表重建
- 不改程式碼

- [ ] **Step 1: 正式 DB（AWS RDS）砍表重建**

在專案根目錄建暫存腳本 `drop_user_account.py`（**用完即刪，不進 git**）：

```python
"""一次性：砍掉舊版 user_account 表，讓 init_db 依新 models.py 重建。"""
from sqlalchemy import text
from backend.core.database import engine

with engine.begin() as conn:
    conn.execute(text("DROP TABLE IF EXISTS user_account"))
print("user_account 已砍除，接著跑 python -m backend.init_db 重建")
```

依序執行：

```bash
uv run python drop_user_account.py
uv run python -m backend.init_db
```

Expected: init_db 輸出「表建立完成」與兩行「帳號建立完成：admin / staff01」。
完成後刪掉 `drop_user_account.py`。

- [ ] **Step 2: 同步 `CLAUDE.md`**

「API 路由」表格中 4 列改成、並加 2 列：

```markdown
| POST   | `/register`            | 需 admin                      | admin 開帳號：employee_id/full_name/role/password/email(選填)，回 201+新帳號資料 |
| POST   | `/login`               | 公開                          | 員編+密碼登入，回 JWT token 與 must_change_password；停用帳號回 401        |
| GET    | `/me`                  | 需登入                        | 回 employee_id / full_name / role（全來自 JWT，不查庫）                    |
| PATCH  | `/me/password`         | 需登入                        | 改自己的密碼（驗舊密碼），成功後 must_change_password 歸 False             |
| PATCH  | `/users/{id}/password` | 需 admin                      | admin 重設員工密碼，成功後 must_change_password 設 True                    |
| DELETE | `/users/{id}`          | 需 admin                      | 軟刪除（is_active=False）；不能停用自己                                    |
```

「資料庫」段落的 user_account 欄位行改成：

```markdown
- **user_account 欄位**：`id`、`employee_id`（unique，登入用員編）、`full_name`、`password`、
  `email`（選填, unique）、`role`（Enum staff/admin）、`must_change_password`、`is_active`、
  `last_login_time`、`company_id`（not null, default 1）
```

- [ ] **Step 3: 通知前端組員（訊息草稿，由使用者送出）**

> 帳號 API 改版上線：①登入帳號改員編（欄位統一叫 `employee_id`，`AuthSession` 預留的
> `employee_code` 請改名）②JWT payload 多 `full_name`（`display_name` 別再拿 `sub`）
> ③login 回應多 `must_change_password`，true 時請導去改密碼頁，改密碼打
> `PATCH /me/password`（舊密碼錯回 400）④`GET /me` 回
> `{employee_id, full_name, role}`。規格見 backend/docs/superpowers/specs/2026-07-17-account-redesign-design.md

- [ ] **Step 4: 手動煙霧測試（對著正式 DB）**

```bash
uv run uvicorn backend.main:app --reload
```

開 http://127.0.0.1:8000/docs，依序驗證：

1. `POST /login`（admin / 123456）→ 200，回應含 `"must_change_password": false`
2. 用該 token `POST /register` 開一個 `E001`（臨時密碼 temp66）→ 201
3. `POST /login`（E001 / temp66）→ `"must_change_password": true`
4. 用 E001 的 token `PATCH /me/password`（temp66 → mypw66）→ 200；重新登入 → false
5. 用 admin token `DELETE /users/{E001 的 id}` → 200；E001 再登入 → 401

- [ ] **Step 5: 跑最後一次全套測試 + 提醒使用者 commit**

Run: `uv run pytest -v`
Expected: 全部 PASS

建議訊息：`docs: 同步帳號改版後的 CLAUDE.md 路由與資料庫說明`

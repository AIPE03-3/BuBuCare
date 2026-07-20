# 前端串接補齊（devices / users / reports）實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 補齊前端整合文件盤點出的三組端點：`GET/PATCH /devices`、`GET/PATCH /users`、通報單 `POST/GET /events/{event_id}/reports`（含新表 `detect_event_reports`）。

**Architecture:** 照 feature-based 慣例，`devices/`、`reports/` 各開新資料夾（router 一檔搞定），users 兩支加在既有 `backend/users/router.py`。通報單整包存 JSON（定義權在前端），`report_type` 抽出成欄。規格見 `backend/docs/superpowers/specs/2026-07-20-frontend-gap-endpoints-design.md`。

**Tech Stack:** FastAPI + SQLAlchemy 2.0（Mapped/mapped_column）+ pytest（in-memory SQLite）

## Global Constraints

- 測試指令：`uv run pytest backend/tests/<檔名> -v`（PowerShell 全新 session 用完整路徑：`& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest ...`）
- **commit 一律由使用者執行**：每個 Task 結束時停下來提醒，不要自己跑 git commit；commit 訊息不加模型署名
- 依專案規矩：test 相關 step 可連續跑；**寫正式檔案（backend/ 下非 tests 的檔案）前、每個 Task 做完後，停下來讓使用者確認**
- 固定選項欄位用原生 SQLAlchemy `Enum` + `create_constraint=True`（專案既定慣例）
- 權限依賴沿用 `backend/core/dependencies.py` 的 `get_current_user` / `require_admin`
- 種子資料（conftest）：Device 1「交誼廳-01」掛 Location 1「交誼廳」（floor 未設＝None）；帳號 alice/staff、boss/admin

---

### Task 1: `GET /devices`（新資料夾 backend/devices/）

**Files:**
- Create: `backend/devices/__init__.py`（空檔）
- Create: `backend/devices/router.py`
- Modify: `backend/main.py`（掛 router）
- Test: `backend/tests/test_devices.py`

**Interfaces:**
- Consumes: `Device`（含 `location` relationship）、`get_current_user`、`get_db`
- Produces: `backend/devices/router.py` 的 `router`（APIRouter）與 `serialize_device(device) -> dict`（Task 2 沿用）

- [ ] **Step 1: 寫失敗測試**

`backend/tests/test_devices.py`：

```python
# test_devices.py
# 測試 GET /devices：鏡頭清單（JOIN locations 夾帶位置資訊）

from backend.core.models import Device, Location


def test_get_devices_returns_seed_device(client, auth_headers):
    # 登入後查清單 → 200，種子裝置的欄位形狀正確
    res = client.get("/devices", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    first = data[0]
    assert first == {
        "device_id": 1,
        "device_name": "交誼廳-01",
        "location": "交誼廳",
        "floor": None,          # 種子 Location 沒設樓層
        "stream_url": None,
        "status": "active",
    }


def test_get_devices_includes_floor(client, auth_headers, db_session):
    # 位置有設樓層時，floor 帶出字串
    db_session.add(Location(location_id=2, location_name="復健室", floor="2F", company_id=1))
    db_session.add(Device(device_id=2, device_name="復健室-01", location_id=2,
                          status="active", company_id=1))
    db_session.commit()

    res = client.get("/devices", headers=auth_headers)
    target = next(d for d in res.json() if d["device_id"] == 2)
    assert target["location"] == "復健室"
    assert target["floor"] == "2F"


def test_get_devices_without_location_returns_null(client, auth_headers, db_session):
    # 裝置沒設位置（location_id 為 NULL）→ location / floor 都回 null
    db_session.add(Device(device_id=3, device_name="倉庫-01",
                          status="active", company_id=1))
    db_session.commit()

    res = client.get("/devices", headers=auth_headers)
    target = next(d for d in res.json() if d["device_id"] == 3)
    assert target["location"] is None
    assert target["floor"] is None


def test_get_devices_requires_login(client):
    # 沒帶 token → 401
    res = client.get("/devices")
    assert res.status_code == 401
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest backend/tests/test_devices.py -v`
Expected: 4 個測試 FAIL（404 Not Found——路由還不存在）

- [ ] **Step 3: 寫實作**（寫正式檔案前先停下來給使用者看）

`backend/devices/__init__.py`：空檔。

`backend/devices/router.py`：

```python
# backend/devices/router.py
# 裝置（鏡頭）相關路由。前端「鏡頭清單」頁面的資料來源
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.dependencies import get_current_user
from backend.core.models import Device

router = APIRouter()


def serialize_device(device: Device) -> dict:
    # 裝置的統一 JSON 結構：位置資訊 JOIN 好夾帶，前端不用再查
    # status 回後端字彙（active/inactive/fault），前端在他們的 api 層對照成 online/offline/disabled
    return {
        "device_id": device.device_id,
        "device_name": device.device_name,
        "location": device.location.location_name if device.location else None,
        "floor": device.location.floor if device.location else None,
        "stream_url": device.stream_url,
        "status": device.status,
    }


# ════════════════════════════════════════════════════════
# GET /devices（登入即可）：全部裝置清單
# ════════════════════════════════════════════════════════
@router.get("/devices")
def list_devices(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    devices = db.query(Device).order_by(Device.device_id).all()
    return [serialize_device(d) for d in devices]
```

`backend/main.py` 兩處修改：

```python
from backend.devices.router import router as device_router
```

```python
app.include_router(device_router)  # 裝置：鏡頭清單 / 改名
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest backend/tests/test_devices.py -v`
Expected: 4 passed

- [ ] **Step 5: 跑全部測試確認沒弄壞別人**

Run: `uv run pytest -v`
Expected: all passed

- [ ] **Step 6: 停下來——提醒使用者 commit（訊息建議：`feat: 新增 GET /devices 鏡頭清單端點`）**

---

### Task 2: `PATCH /devices/{device_id}`（改名，admin）

**Files:**
- Modify: `backend/devices/router.py`（加一個路由）
- Test: `backend/tests/test_devices_rename.py`

**Interfaces:**
- Consumes: Task 1 的 `serialize_device`、`require_admin`
- Produces: 無（終端端點）

- [ ] **Step 1: 寫失敗測試**

`backend/tests/test_devices_rename.py`：

```python
# test_devices_rename.py
# 測試 PATCH /devices/{device_id}：admin 改鏡頭名稱

from backend.core.models import Device


def _admin_token(client):
    login = client.post("/login", data={"username": "boss", "password": "adminpass"})
    return login.json()["access_token"]


def test_admin_renames_device(client, db_session):
    # admin 改名 → 200，回應與 DB 都是新名字
    token = _admin_token(client)
    res = client.patch("/devices/1", json={"device_name": "交誼廳-东侧"},
                       headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["device_name"] == "交誼廳-东侧"
    assert res.json()["location"] == "交誼廳"  # 其他欄位照常帶出

    db_session.expire_all()
    device = db_session.query(Device).filter(Device.device_id == 1).first()
    assert device.device_name == "交誼廳-东侧"


def test_rename_unknown_device_returns_404(client):
    token = _admin_token(client)
    res = client.patch("/devices/999", json={"device_name": "幽靈鏡頭"},
                       headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 404


def test_staff_cannot_rename_returns_403(client, auth_headers):
    # auth_headers 是 staff（alice）的 token
    res = client.patch("/devices/1", json={"device_name": "偷改"}, headers=auth_headers)
    assert res.status_code == 403


def test_empty_name_returns_422(client):
    token = _admin_token(client)
    res = client.patch("/devices/1", json={"device_name": ""},
                       headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 422


def test_rename_requires_login(client):
    res = client.patch("/devices/1", json={"device_name": "沒登入"})
    assert res.status_code == 401
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest backend/tests/test_devices_rename.py -v`
Expected: FAIL（405 或 404——PATCH 路由還不存在）

- [ ] **Step 3: 寫實作**（寫正式檔案前先停下來給使用者看）

`backend/devices/router.py` 追加（import 區補 `HTTPException`、`BaseModel`、`Field`、`require_admin`）：

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.dependencies import get_current_user, require_admin
```

```python
# ── PATCH /devices/{device_id} 收到的 JSON 格式 ──
# 只收 device_name：location/floor 是 locations 表的欄位，從裝置端點改會波及
# 同區域所有裝置與歷史事件的顯示位置（location_id 凍結設計），區域管理是獨立功能
class DeviceRenameRequest(BaseModel):
    device_name: str = Field(min_length=1)


# ════════════════════════════════════════════════════════
# PATCH /devices/{device_id}（需 admin）：改鏡頭名稱
# ════════════════════════════════════════════════════════
@router.patch("/devices/{device_id}")
def rename_device(
    device_id: int,
    body: DeviceRenameRequest,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if device is None:
        raise HTTPException(status_code=404, detail="裝置不存在")

    device.device_name = body.device_name
    db.commit()
    db.refresh(device)
    return serialize_device(device)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest backend/tests/test_devices_rename.py -v`
Expected: 5 passed

- [ ] **Step 5: 跑全部測試**

Run: `uv run pytest -v`
Expected: all passed

- [ ] **Step 6: 停下來——提醒使用者 commit（訊息建議：`feat: 新增 PATCH /devices/{id} 鏡頭改名端點`）**

---

### Task 3: `GET /users`（使用者名單，admin）

**Files:**
- Modify: `backend/users/router.py`（加一個路由）
- Test: `backend/tests/test_users_list.py`

**Interfaces:**
- Consumes: `User`、`require_admin`
- Produces: 回應形狀 `[{id, employee_id, full_name, role}]`（Task 4 的回應與此一致）

- [ ] **Step 1: 寫失敗測試**

`backend/tests/test_users_list.py`：

```python
# test_users_list.py
# 測試 GET /users：admin 查使用者名單（只回未停用帳號、永不回傳 password）

from backend.core.models import User


def _admin_token(client):
    login = client.post("/login", data={"username": "boss", "password": "adminpass"})
    return login.json()["access_token"]


def test_admin_lists_active_users(client):
    # admin 查名單 → 200，含種子兩帳號，欄位形狀正確
    token = _admin_token(client)
    res = client.get("/users", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    by_employee_id = {u["employee_id"]: u for u in data}
    assert set(by_employee_id.keys()) == {"alice", "boss"}
    alice = by_employee_id["alice"]
    assert set(alice.keys()) == {"id", "employee_id", "full_name", "role"}  # 白名單四欄
    assert alice["full_name"] == "愛麗絲"
    assert alice["role"] == "staff"


def test_deactivated_user_not_listed(client, db_session):
    # 停用的帳號不出現在名單
    alice = db_session.query(User).filter(User.employee_id == "alice").first()
    alice.is_active = False
    db_session.commit()

    token = _admin_token(client)
    res = client.get("/users", headers={"Authorization": f"Bearer {token}"})
    ids = [u["employee_id"] for u in res.json()]
    assert "alice" not in ids
    assert "boss" in ids


def test_response_never_contains_password(client):
    # 任何一筆都不能出現 password 欄位（連雜湊值也不行）
    token = _admin_token(client)
    res = client.get("/users", headers={"Authorization": f"Bearer {token}"})
    for user in res.json():
        assert "password" not in user


def test_staff_cannot_list_users_returns_403(client, auth_headers):
    res = client.get("/users", headers=auth_headers)
    assert res.status_code == 403


def test_list_users_requires_login(client):
    res = client.get("/users")
    assert res.status_code == 401
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest backend/tests/test_users_list.py -v`
Expected: FAIL（405 Method Not Allowed——`/users` 只有底下的子路徑，還沒有 GET）

- [ ] **Step 3: 寫實作**（寫正式檔案前先停下來給使用者看）

`backend/users/router.py` 追加（放在 DELETE /users/{user_id} 附近，同一掛管理功能）：

```python
# ════════════════════════════════════════════════════════
# 路由七：GET /users（需 admin；使用者管理名單）
# ════════════════════════════════════════════════════════
@router.get("/users")
def list_users(current_user: dict = Depends(require_admin), db: Session = Depends(get_db)):
    # 只回未停用帳號：停用的不該出現在管理名單（前端也沒有「停用中」的顯示）
    users = db.query(User).filter(User.is_active == True).order_by(User.id).all()  # noqa: E712
    # 白名單式只挑四欄吐出去，回應永遠不會出現 password（連雜湊值都不給）
    return [
        {"id": u.id, "employee_id": u.employee_id, "full_name": u.full_name, "role": u.role}
        for u in users
    ]
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest backend/tests/test_users_list.py -v`
Expected: 5 passed

- [ ] **Step 5: 跑全部測試**

Run: `uv run pytest -v`
Expected: all passed

- [ ] **Step 6: 停下來——提醒使用者 commit（訊息建議：`feat: 新增 GET /users 使用者名單端點`）**

---

### Task 4: `PATCH /users/{user_id}`（改姓名，admin）

**Files:**
- Modify: `backend/users/router.py`（加一個路由）
- Test: `backend/tests/test_users_update.py`

**Interfaces:**
- Consumes: `User`、`require_admin`；回應形狀與 Task 3 單筆一致
- Produces: 無（終端端點）

- [ ] **Step 1: 寫失敗測試**

`backend/tests/test_users_update.py`：

```python
# test_users_update.py
# 測試 PATCH /users/{user_id}：admin 改使用者姓名（只收 full_name）
# 密碼不從這支走：重設密碼已有專屬端點 /users/{id}/password（含 must_change_password 行為）

from backend.core.models import User


def _admin_token(client):
    login = client.post("/login", data={"username": "boss", "password": "adminpass"})
    return login.json()["access_token"]


def test_admin_updates_full_name(client, db_session):
    alice = db_session.query(User).filter(User.employee_id == "alice").first()
    token = _admin_token(client)
    res = client.patch(f"/users/{alice.id}", json={"full_name": "愛麗絲·王"},
                       headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json() == {"id": alice.id, "employee_id": "alice",
                          "full_name": "愛麗絲·王", "role": "staff"}

    db_session.expire_all()
    after = db_session.query(User).filter(User.employee_id == "alice").first()
    assert after.full_name == "愛麗絲·王"


def test_update_unknown_user_returns_404(client):
    token = _admin_token(client)
    res = client.patch("/users/999", json={"full_name": "查無此人"},
                       headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 404


def test_role_field_is_ignored(client, db_session):
    # 就算多塞 role 欄位也不會被改：防權限竄改（Pydantic 模型只收 full_name）
    alice = db_session.query(User).filter(User.employee_id == "alice").first()
    token = _admin_token(client)
    res = client.patch(f"/users/{alice.id}",
                       json={"full_name": "愛麗絲", "role": "admin"},
                       headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200

    db_session.expire_all()
    after = db_session.query(User).filter(User.employee_id == "alice").first()
    assert after.role == "staff"  # role 沒被動


def test_empty_full_name_returns_422(client, db_session):
    alice = db_session.query(User).filter(User.employee_id == "alice").first()
    token = _admin_token(client)
    res = client.patch(f"/users/{alice.id}", json={"full_name": ""},
                       headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 422


def test_staff_cannot_update_returns_403(client, auth_headers, db_session):
    alice = db_session.query(User).filter(User.employee_id == "alice").first()
    res = client.patch(f"/users/{alice.id}", json={"full_name": "偷改"}, headers=auth_headers)
    assert res.status_code == 403
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest backend/tests/test_users_update.py -v`
Expected: FAIL（405——`/users/{user_id}` 只有 DELETE，還沒有 PATCH）

- [ ] **Step 3: 寫實作**（寫正式檔案前先停下來給使用者看）

`backend/users/router.py` 追加：

```python
class UpdateUserRequest(BaseModel):
    # 只收 full_name：不收 role（防權限竄改）、不收密碼（重設密碼走專屬端點）
    full_name: str = Field(min_length=1)


# ════════════════════════════════════════════════════════
# 路由八：PATCH /users/{user_id}（需 admin；改使用者姓名）
# ════════════════════════════════════════════════════════
@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UpdateUserRequest,
                current_user: dict = Depends(require_admin),
                db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="找不到使用者")

    user.full_name = body.full_name
    db.commit()
    db.refresh(user)
    return {"id": user.id, "employee_id": user.employee_id,
            "full_name": user.full_name, "role": user.role}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest backend/tests/test_users_update.py -v`
Expected: 5 passed

- [ ] **Step 5: 跑全部測試**

Run: `uv run pytest -v`
Expected: all passed

- [ ] **Step 6: 停下來——提醒使用者 commit（訊息建議：`feat: 新增 PATCH /users/{id} 改姓名端點`）**

---

### Task 5: 新表 `detect_event_reports`（model）

**Files:**
- Modify: `backend/core/models.py`（加 `DetectEventReport` 類別、import `JSON`）
- Test: `backend/tests/test_models.py`（追加一個測試）

**Interfaces:**
- Consumes: `Base`、既有 `DetectEvent` / `User` 表（FK 目標）
- Produces: `DetectEventReport`（欄位：`report_id: int PK` / `event_id: str` / `report_type: str` / `form: dict` / `created_by: str` / `created_at: datetime`），Task 6、7 依賴

**部署備註**：新表由 `main.py` 啟動時的 `Base.metadata.create_all` 自動建立（或跑 `python -m backend.init_db`），不需要補欄位邏輯。

- [ ] **Step 1: 寫失敗測試**

`backend/tests/test_models.py` 檔尾追加：

```python
def test_detect_event_report_roundtrip(db_session, make_event):
    # 通報單：form 整包 JSON 存進去，讀回來還是 dict、內容不變
    from backend.core.models import DetectEventReport
    from datetime import datetime

    event = make_event()
    report = DetectEventReport(
        event_id=event.event_id,
        report_type="initial",
        form={"caseName": "王小明", "reportType": "初報", "handling": ["送醫治療"]},
        created_by="alice",
        created_at=datetime(2026, 7, 20, 10, 0),
    )
    db_session.add(report)
    db_session.commit()
    db_session.refresh(report)

    assert report.report_id == 1                      # 自動編號 PK
    assert report.form["caseName"] == "王小明"        # JSON 欄位讀寫是 dict
    assert report.form["handling"] == ["送醫治療"]    # 巢狀結構原樣保存
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest backend/tests/test_models.py -v`
Expected: 新測試 FAIL（ImportError: cannot import name 'DetectEventReport'）

- [ ] **Step 3: 寫實作**（寫正式檔案前先停下來給使用者看）

`backend/core/models.py`：import 行補 `JSON`：

```python
from sqlalchemy import Integer, String, DateTime, Float, Text, ForeignKey, Enum, Boolean, JSON
```

檔尾追加：

```python
class DetectEventReport(Base):  # 事件通報單：每次儲存獨立一筆（初報/續報/結報累積，不覆蓋）
    __tablename__ = "detect_event_reports"

    report_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("detect_events.event_id"), nullable=False
    )
    # 初報/續報/結報。抽出成欄是因為要獨立查詢；其餘表單內容不查、整包存 form
    report_type: Mapped[str] = mapped_column(
        Enum("initial", "follow_up", "final", name="report_type", create_constraint=True),
        nullable=False,
    )
    # 表單整包 JSON 保管：定義權在前端（政府制式表單），表單改版後端零修改
    form: Mapped[dict] = mapped_column(JSON, nullable=False)
    # 誰存的誰負責：從 JWT 的 sub 記員編，前端不帶（同 verdict_by/resolved_by 模式）
    created_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("user_account.employee_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest backend/tests/test_models.py -v`
Expected: all passed（含新測試）

- [ ] **Step 5: 跑全部測試**

Run: `uv run pytest -v`
Expected: all passed

- [ ] **Step 6: 停下來——提醒使用者 commit（訊息建議：`feat: 新增 detect_event_reports 通報單資料表`）**

---

### Task 6: `POST /events/{event_id}/reports`（存通報單）

**Files:**
- Create: `backend/reports/__init__.py`（空檔）
- Create: `backend/reports/router.py`
- Modify: `backend/main.py`（掛 router）
- Test: `backend/tests/test_reports_post.py`

**Interfaces:**
- Consumes: Task 5 的 `DetectEventReport`、`DetectEvent`、`get_current_user`
- Produces: `backend/reports/router.py` 的 `router`（APIRouter）與 `serialize_report(report) -> dict`（Task 7 沿用）

- [ ] **Step 1: 寫失敗測試**

`backend/tests/test_reports_post.py`：

```python
# test_reports_post.py
# 測試 POST /events/{event_id}/reports：存通報單
# form 整包 JSON 原樣保管；created_by 由後端從 JWT 記（誰存的誰負責）

from backend.core.models import DetectEventReport

FORM = {"caseName": "王小明", "reportType": "初報", "handling": ["送醫治療"]}


def test_save_report_returns_201(client, auth_headers, make_event):
    event = make_event()
    res = client.post(f"/events/{event.event_id}/reports",
                      json={"report_type": "initial", "form": FORM},
                      headers=auth_headers)
    assert res.status_code == 201
    data = res.json()
    assert data["event_id"] == event.event_id
    assert data["report_type"] == "initial"
    assert data["form"] == FORM                 # 整包原樣存、原樣回
    assert data["created_by"] == "alice"        # 從 JWT 記，不是前端帶的
    assert data["created_at"] is not None


def test_reports_accumulate_not_overwrite(client, auth_headers, make_event, db_session):
    # 同事件存兩筆 → 兩筆都在（不覆蓋），且同類型也可重複
    event = make_event()
    client.post(f"/events/{event.event_id}/reports",
                json={"report_type": "initial", "form": FORM}, headers=auth_headers)
    client.post(f"/events/{event.event_id}/reports",
                json={"report_type": "follow_up", "form": FORM}, headers=auth_headers)

    count = db_session.query(DetectEventReport).filter(
        DetectEventReport.event_id == event.event_id).count()
    assert count == 2


def test_save_report_unknown_event_returns_404(client, auth_headers):
    res = client.post("/events/no-such-event/reports",
                      json={"report_type": "initial", "form": FORM},
                      headers=auth_headers)
    assert res.status_code == 404


def test_invalid_report_type_returns_422(client, auth_headers, make_event):
    event = make_event()
    res = client.post(f"/events/{event.event_id}/reports",
                      json={"report_type": "第一次通報", "form": FORM},  # 要收英文 enum
                      headers=auth_headers)
    assert res.status_code == 422


def test_save_report_requires_login(client, make_event):
    event = make_event()
    res = client.post(f"/events/{event.event_id}/reports",
                      json={"report_type": "initial", "form": FORM})
    assert res.status_code == 401
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest backend/tests/test_reports_post.py -v`
Expected: FAIL（404——路由還不存在；注意 404 測試此時也會「假通過」，實作後才有意義）

- [ ] **Step 3: 寫實作**（寫正式檔案前先停下來給使用者看）

`backend/reports/__init__.py`：空檔。

`backend/reports/router.py`：

```python
# backend/reports/router.py
# 通報單路由：存（POST）與查（GET）。表單整包 JSON 保管，定義權在前端
# 設計規格：backend/docs/superpowers/specs/2026-07-20-frontend-gap-endpoints-design.md
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.dependencies import get_current_user
from backend.core.models import DetectEvent, DetectEventReport

router = APIRouter()


def serialize_report(report: DetectEventReport) -> dict:
    return {
        "report_id": report.report_id,
        "event_id": report.event_id,
        "report_type": report.report_type,
        "form": report.form,
        "created_by": report.created_by,
        "created_at": report.created_at.isoformat(),
    }


def get_event_or_404(db: Session, event_id: str) -> DetectEvent:
    event = db.query(DetectEvent).filter(DetectEvent.event_id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="事件不存在")
    return event


# ── POST /events/{event_id}/reports 收到的 JSON 格式 ──
# form 不驗內容：表單定義權在前端，後端只保管；report_type 用 Literal 擋非法值
class ReportCreateRequest(BaseModel):
    report_type: Literal["initial", "follow_up", "final"]
    form: dict


# ════════════════════════════════════════════════════════
# POST /events/{event_id}/reports（登入即可）：存一筆通報單
# ════════════════════════════════════════════════════════
@router.post("/events/{event_id}/reports", status_code=201)
def create_report(
    event_id: str,
    body: ReportCreateRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_event_or_404(db, event_id)

    report = DetectEventReport(
        event_id=event_id,
        report_type=body.report_type,
        form=body.form,
        created_by=current_user["sub"],  # 誰存的誰負責，從 JWT 記
        created_at=datetime.now(),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return serialize_report(report)
```

`backend/main.py` 兩處修改：

```python
from backend.reports.router import router as report_router
```

```python
app.include_router(report_router)  # 通報單：存 / 查
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest backend/tests/test_reports_post.py -v`
Expected: 5 passed

- [ ] **Step 5: 跑全部測試**

Run: `uv run pytest -v`
Expected: all passed

- [ ] **Step 6: 停下來——提醒使用者 commit（訊息建議：`feat: 新增 POST /events/{id}/reports 存通報單端點`）**

---

### Task 7: `GET /events/{event_id}/reports`（查通報單，舊→新）

**Files:**
- Modify: `backend/reports/router.py`（加一個路由）
- Test: `backend/tests/test_reports_get.py`

**Interfaces:**
- Consumes: Task 6 的 `serialize_report`、`get_event_or_404`
- Produces: 無（終端端點）

- [ ] **Step 1: 寫失敗測試**

`backend/tests/test_reports_get.py`：

```python
# test_reports_get.py
# 測試 GET /events/{event_id}/reports：查某事件全部通報單
# 排序契約：舊→新（前端 getLatestReport 取陣列最後一筆當最新，順序錯了會默默拿到舊資料）

from datetime import datetime

from backend.core.models import DetectEventReport


def _insert_report(db_session, event_id, report_type, created_at):
    # 直接塞 DB 指定 created_at，排序測試才有確定的先後
    report = DetectEventReport(
        event_id=event_id, report_type=report_type,
        form={"note": report_type}, created_by="alice", created_at=created_at,
    )
    db_session.add(report)
    db_session.commit()


def test_reports_sorted_old_to_new(client, auth_headers, make_event, db_session):
    event = make_event()
    # 故意亂序塞入：新的先塞、舊的後塞
    _insert_report(db_session, event.event_id, "final", datetime(2026, 7, 22, 9, 0))
    _insert_report(db_session, event.event_id, "initial", datetime(2026, 7, 20, 9, 0))
    _insert_report(db_session, event.event_id, "follow_up", datetime(2026, 7, 21, 9, 0))

    res = client.get(f"/events/{event.event_id}/reports", headers=auth_headers)
    assert res.status_code == 200
    types = [r["report_type"] for r in res.json()]
    assert types == ["initial", "follow_up", "final"]  # 回應照時間舊→新


def test_no_reports_returns_empty_list(client, auth_headers, make_event):
    event = make_event()
    res = client.get(f"/events/{event.event_id}/reports", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []


def test_get_reports_unknown_event_returns_404(client, auth_headers):
    res = client.get("/events/no-such-event/reports", headers=auth_headers)
    assert res.status_code == 404


def test_get_reports_only_own_event(client, auth_headers, make_event, db_session):
    # 只回該事件的通報單，別的事件的不混進來
    event_a = make_event()
    event_b = make_event()
    _insert_report(db_session, event_a.event_id, "initial", datetime(2026, 7, 20, 9, 0))
    _insert_report(db_session, event_b.event_id, "initial", datetime(2026, 7, 20, 9, 0))

    res = client.get(f"/events/{event_a.event_id}/reports", headers=auth_headers)
    assert len(res.json()) == 1
    assert res.json()[0]["event_id"] == event_a.event_id


def test_get_reports_requires_login(client, make_event):
    event = make_event()
    res = client.get(f"/events/{event.event_id}/reports")
    assert res.status_code == 401
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest backend/tests/test_reports_get.py -v`
Expected: FAIL（405 或 404——GET 路由還不存在）

- [ ] **Step 3: 寫實作**（寫正式檔案前先停下來給使用者看）

`backend/reports/router.py` 追加：

```python
# ════════════════════════════════════════════════════════
# GET /events/{event_id}/reports（登入即可）：查某事件全部通報單
# ════════════════════════════════════════════════════════
@router.get("/events/{event_id}/reports")
def list_reports(
    event_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_event_or_404(db, event_id)

    # 排序契約：舊→新（初報→續報→結報的歷程順序）。
    # 前端 getLatestReport 取陣列最後一筆當最新，這個順序不能反。
    # 同一秒存兩筆時用 report_id（自動編號）決勝，保證順序穩定
    reports = (
        db.query(DetectEventReport)
        .filter(DetectEventReport.event_id == event_id)
        .order_by(DetectEventReport.created_at.asc(), DetectEventReport.report_id.asc())
        .all()
    )
    return [serialize_report(r) for r in reports]
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest backend/tests/test_reports_get.py -v`
Expected: 5 passed

- [ ] **Step 5: 跑全部測試（收尾總驗證）**

Run: `uv run pytest -v`
Expected: all passed

- [ ] **Step 6: 停下來——提醒使用者 commit（訊息建議：`feat: 新增 GET /events/{id}/reports 查通報單端點`）**

---

## 收尾（全部 Task 完成後）

- [ ] 更新 `CLAUDE.md` 的 API 路由表：補 6 個新端點一行一個（格式照既有表格）
- [ ] 提醒使用者：把 spec「給前端的對齊清單」6 條轉達給前端（status 對照、使用者欄位對照、密碼最少 6 碼、report_type 英文值、409 待確認、staff_id 已改 verdict_by/resolved_by）
- [ ] 提醒使用者：正式 RDS 建新表——重啟服務（create_all）或跑 `python -m backend.init_db` 即可
- [ ] 列出本輪產生/改動檔案清單給使用者（建議保留/可刪除）

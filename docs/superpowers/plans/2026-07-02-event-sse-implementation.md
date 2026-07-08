# 跌倒事件通報 + SSE 推播 + 人工確認 — 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 實作 spec（`docs/superpowers/specs/2026-07-02-event-sse-design.md`）定義的事件通報流程：POST /events 收事件 → 存 DB → SSE 廣播 → 人工判定/結案。

**Architecture:** 事件「入口」（POST /events）與「處理」（`handle_incoming_event()`：存 DB + 廣播）拆開，未來 Kafka consumer 直接呼叫處理函式。SSE 用全域連線池（每連線一個 asyncio.Queue），先存 DB 成功才廣播。

**Tech Stack:** FastAPI（既有）、SQLAlchemy 2.0 style（Mapped/mapped_column，跟 models.py 現有寫法一致）、pytest + TestClient + in-memory SQLite（跟 tests/conftest.py 現有模式一致）。**不新增任何套件**——SSE 用 FastAPI 內建 StreamingResponse。

## Global Constraints

- 一切以 spec 為準：`docs/superpowers/specs/2026-07-02-event-sse-design.md`
- 測試指令一律用完整路徑：`& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest ...`（PowerShell 每次是新 session，不繼承 venv）
- 禁用 `uv run`（本機有 trampoline bug）
- bcrypt 鎖定 4.0.1，不得升級
- 不新增任何 pip 套件
- 註解風格跟既有檔案一致：中文白話註解，解釋「為什麼」
- 先存 DB 成功才廣播；狀態轉換規則只寫在後端，違反回 409
- `status` 值：`pending` / `in_progress` / `resolved`；`verdict` 值：`null` / `true_alarm` / `false_alarm`
- ~~spec 裡的 ENUM 欄位一律用 `String` + 應用層驗證實作~~ **（2026-07-03 執行時變更：使用者決定改用原生 SQLAlchemy `Enum` + `create_constraint=True`——PostgreSQL 建真 ENUM 型別、SQLite 用 CHECK 約束，程式端仍是字串值；Pydantic `Literal` 應用層驗證照舊保留）**
- POST /events 不接受外部指定 status，一律後端設 `pending`
- 使用者是邊學邊做：實作時每一步先用白話說明、取得同意再動手（CLAUDE.md 合作規則）

---

### Task 1: 資料模型（5 張新表 + user_account 加 company_id）

**Files:**
- Modify: `models.py`（加 4 個 class + User 加一欄）
- Modify: `tests/conftest.py`（種子資料加公司/裝置/照護員 + 新 fixtures）
- Test: `tests/test_models.py`（新建）

**Interfaces:**
- Produces: `models.Company(company_id, company_name)`、`models.Location(location_id, location_name, company_id)`、`models.Device(device_id, device_name, location_id, status, stream_url, company_id)`（含 `Device.location` relationship，可直接讀 `device.location.location_name`）、`models.Staff(staff_id, staff_name, company_id)`、`models.DetectEvent(event_id: str UUID, device_id, event_type, status, verdict, clip_path, snapshot_path, detected_at, staff_id, company_id, yolo_score, yolo_threshold, vlm_summary, severity)`、`User.company_id: int (default 1)`
- Produces（conftest）: 種子＝公司 id=1「測試安養院」、區域 id=1「交誼廳」、裝置 id=1「交誼廳-01」（location_id=1）、照護員 id=1「小美」/ id=2「阿強」；fixtures `staff_token`、`auth_headers`、`make_event`；環境變數 `EVENT_API_KEY=test-api-key`

- [x] **Step 1: 寫失敗測試**

建立 `tests/test_models.py`：

```python
# 測資料模型：新表能建立、預設值正確、種子資料有進去
from datetime import datetime
from models import Company, Location, Device, Staff, DetectEvent, User


def test_建立事件_預設狀態是pending(db_session):
    event = DetectEvent(
        device_id=1,
        event_type="fall",
        clip_path="s3://clips/e1.mp4",
        detected_at=datetime(2026, 7, 2, 14, 30),
        company_id=1,
    )
    db_session.add(event)
    db_session.commit()
    db_session.refresh(event)

    assert event.event_id  # UUID 字串自動產生
    assert event.status == "pending"   # 後端預設，不靠外部指定
    assert event.verdict is None       # 還沒人判定
    assert event.staff_id is None      # 還沒指派照護員


def test_種子資料存在(db_session):
    assert db_session.query(Company).count() == 1
    device = db_session.query(Device).filter_by(device_id=1).first()
    assert device.device_name == "交誼廳-01"
    # relationship：透過 device.location_id 自動查 locations 表拿名稱
    assert device.location.location_name == "交誼廳"
    assert db_session.query(Staff).count() == 2


def test_既有帳號自動掛預設公司(db_session):
    alice = db_session.query(User).filter_by(name="alice").first()
    assert alice.company_id == 1
```

- [x] **Step 2: 跑測試確認失敗**

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/test_models.py -v
```

預期：FAIL，`ImportError: cannot import name 'Company' from 'models'`

- [x] **Step 3: 實作 models.py**

在 `models.py` 檔頭 import 區改成：

```python
# models.py
import uuid
from typing import Optional
from datetime import datetime
from sqlalchemy import Integer, String, DateTime, Float, Text, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped, relationship
from database import Base
```

`User` class 裡加一欄（放在 `last_login_time` 之後）：

```python
    # 所屬機構。default=1 表示新帳號自動掛預設公司，多租戶邏輯未來才做
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.company_id"), nullable=False, default=1
    )
```

檔案末尾加 4 個新 class：

```python
class Company(Base):  # 安養院（多租戶預留，本輪只有一筆預設公司 id=1）
    __tablename__ = "companies"

    company_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)


class Location(Base):  # 區域（交誼廳、走廊…）：獨立成表讓名稱統一，只被 devices 引用、不連 events
    __tablename__ = "locations"

    location_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    location_name: Mapped[str] = mapped_column(String(50), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"), nullable=False)


class Device(Base):  # 攝影機裝置
    __tablename__ = "devices"

    device_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # location_id 和 stream_url 是 spec 裡唯二可空的欄位：裝置剛建檔時可能還沒定位置、還沒接串流
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("locations.location_id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")  # active/inactive/fault
    stream_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"), nullable=False)

    # 關聯屬性：程式可直接寫 device.location.location_name，SQLAlchemy 依 location_id 自動查
    location: Mapped[Optional["Location"]] = relationship("Location")


class Staff(Base):  # 照護員：被指派去現場處理的人（跟 user_account 的登入帳號是兩回事）
    __tablename__ = "staff"

    staff_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    staff_name: Mapped[str] = mapped_column(String(50), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"), nullable=False)


class DetectEvent(Base):  # 跌倒事件主表
    __tablename__ = "detect_events"

    # UUID 存成 36 字元字串，SQLite（測試）和 PostgreSQL（正式）都通用
    event_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.device_id"), nullable=False)
    event_type: Mapped[Optional[str]] = mapped_column(String(50))  # 例如 fall

    # 拆兩欄的狀態機：status 管進度，verdict 管人工判定結果
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending/in_progress/resolved
    verdict: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # true_alarm/false_alarm

    clip_path: Mapped[str] = mapped_column(String(255), nullable=False)  # 事件影像片段
    snapshot_path: Mapped[Optional[str]] = mapped_column(String(255))    # 截圖
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    staff_id: Mapped[Optional[int]] = mapped_column(ForeignKey("staff.staff_id"), nullable=True)  # 判真跌倒時指派
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"), nullable=False, default=1)

    yolo_score: Mapped[Optional[float]] = mapped_column(Float)      # 該事件 YOLO 打的分數
    yolo_threshold: Mapped[Optional[float]] = mapped_column(Float)  # 當時的門檻值（門檻日後會調，回訓分析要知道）
    vlm_summary: Mapped[Optional[str]] = mapped_column(Text)        # VLM 情境描述
    severity: Mapped[Optional[str]] = mapped_column(String(10))     # low/medium/high
```

- [x] **Step 4: 更新 tests/conftest.py**

檔頭 import 改成（多 import 新 model + os + datetime）：

```python
import os
import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# 測試用的機器驗證 key，要在 import main 之前設好（event 端點會從環境變數讀）
os.environ["EVENT_API_KEY"] = "test-api-key"

from main import app
from database import Base, get_db
from models import User, Company, Location, Device, Staff, DetectEvent
from security import hash_password
```

`setup_database` fixture 的種子區塊改成（先種公司，其他資料才有得掛）：

```python
    # 塞入測試用的初始資料：公司 → 裝置/照護員 → 帳號
    db = TestingSessionLocal()
    db.add(Company(company_id=1, company_name="測試安養院"))
    db.commit()  # 先 commit 公司，後面的 FK 才掛得上

    db.add(Location(location_id=1, location_name="交誼廳", company_id=1))
    db.add(Device(device_id=1, device_name="交誼廳-01", location_id=1,
                  status="active", company_id=1))
    db.add(Staff(staff_id=1, staff_name="小美", company_id=1))
    db.add(Staff(staff_id=2, staff_name="阿強", company_id=1))
    db.add(User(name="alice", password=hash_password("secret123"), email="alice@test.com", role="staff"))
    db.add(User(name="boss", password=hash_password("adminpass"), email="boss@test.com", role="admin"))
    db.commit()
    db.close()
```

檔案末尾加三個新 fixtures：

```python
@pytest.fixture
def staff_token(client):
    # 用種子帳號 alice 登入，拿一顆真的 JWT token
    res = client.post("/login", data={"username": "alice", "password": "secret123"})
    return res.json()["access_token"]


@pytest.fixture
def auth_headers(staff_token):
    # 大多數測試用的登入 header
    return {"Authorization": f"Bearer {staff_token}"}


@pytest.fixture
def make_event(db_session):
    # 事件工廠：測試想要什麼狀態的事件，直接在 DB 裡造一筆
    def _make(**kwargs):
        defaults = dict(
            device_id=1,
            event_type="fall",
            clip_path="s3://clips/test.mp4",
            detected_at=datetime(2026, 7, 2, 14, 30),
            company_id=1,
        )
        defaults.update(kwargs)
        event = DetectEvent(**defaults)
        db_session.add(event)
        db_session.commit()
        db_session.refresh(event)
        return event
    return _make
```

- [x] **Step 5: 跑測試確認通過（含既有 16 個測試不能壞）**

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/ -v
```

預期：全部 PASS（既有 16 個 + 新 3 個）

- [x] **Step 6: Commit**

```bash
git add models.py tests/conftest.py tests/test_models.py
git commit -m "feat: 新增 companies/locations/devices/staff/detect_events 資料模型，user_account 加 company_id"
```

---

### Task 2: SSE 連線池（sse.py）

**Files:**
- Create: `sse.py`
- Test: `tests/test_sse.py`（新建）

**Interfaces:**
- Produces: `sse.ConnectionPool`（`register() -> asyncio.Queue`、`unregister(q) -> None`、`broadcast(event_name: str, data: dict) -> None`）、模組層級單例 `sse.pool`、`sse.format_sse(message: dict) -> str`
- 訊息內部格式：`{"event": "event_created"|"event_updated", "data": {完整事件 dict}}`

- [x] **Step 1: 寫失敗測試**

建立 `tests/test_sse.py`：

```python
# 測 SSE 連線池：不開真的網路連線，直接考「信箱投遞」的邏輯
from sse import ConnectionPool, format_sse


def test_廣播_每個連線都收到():
    pool = ConnectionPool()
    q1 = pool.register()
    q2 = pool.register()

    pool.broadcast("event_created", {"event_id": "abc"})

    expected = {"event": "event_created", "data": {"event_id": "abc"}}
    assert q1.get_nowait() == expected
    assert q2.get_nowait() == expected


def test_移除連線後不再收到_其他連線不受影響():
    pool = ConnectionPool()
    q1 = pool.register()
    q2 = pool.register()

    pool.unregister(q1)  # q1 斷線
    pool.broadcast("event_created", {"x": 1})

    assert q1.empty()                          # 斷線的收不到
    assert q2.get_nowait()["data"] == {"x": 1}  # 其他人照收


def test_重複移除不報錯():
    pool = ConnectionPool()
    q = pool.register()
    pool.unregister(q)
    pool.unregister(q)  # 再移除一次，不能爆炸


def test_format_sse_輸出符合SSE格式():
    text = format_sse({"event": "event_created", "data": {"a": 1}})
    assert text == 'event: event_created\ndata: {"a": 1}\n\n'
```

- [x] **Step 2: 跑測試確認失敗**

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/test_sse.py -v
```

預期：FAIL，`ModuleNotFoundError: No module named 'sse'`

- [x] **Step 3: 實作 sse.py**

```python
# sse.py
# SSE 連線池：維護「目前所有連線的信箱（queue）」，事件進來就投遞給每個信箱
# 投遞端（處理 POST/PATCH 的程式）和收件端（/stream 的長連線迴圈）透過 queue 交接，互不等待
import asyncio
import json


class ConnectionPool:
    def __init__(self):
        # 每條 SSE 連線一個 asyncio.Queue（信箱），這個 list 就是連線池
        self.connections: list[asyncio.Queue] = []

    def register(self) -> asyncio.Queue:
        # 新連線進來：生一個信箱掛上清單
        q = asyncio.Queue()
        self.connections.append(q)
        return q

    def unregister(self, q: asyncio.Queue) -> None:
        # 連線斷了：把信箱移出清單。重複移除也不報錯（斷線和重整可能重複觸發）
        if q in self.connections:
            self.connections.remove(q)

    def broadcast(self, event_name: str, data: dict) -> None:
        # 走訪清單，往每個信箱投一份訊息副本
        # list(...) 複製一份再走訪，避免走訪途中有人 unregister 導致 list 長度變動
        message = {"event": event_name, "data": data}
        for q in list(self.connections):
            q.put_nowait(message)


# 全域單例：整個 app 共用同一個連線池（方案 A：單機記憶體，未來擴展換 Redis Pub/Sub）
pool = ConnectionPool()


def format_sse(message: dict) -> str:
    # 把內部訊息格式轉成 SSE 協定的純文字格式
    # ensure_ascii=False 讓中文直接輸出；default=str 讓 datetime 等型別自動轉字串
    data = json.dumps(message["data"], ensure_ascii=False, default=str)
    return f"event: {message['event']}\ndata: {data}\n\n"
```

- [x] **Step 4: 跑測試確認通過**

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/test_sse.py -v
```

預期：4 個全 PASS

- [x] **Step 5: Commit**

```bash
git add sse.py tests/test_sse.py
git commit -m "feat: SSE 連線池（register/unregister/broadcast + SSE 格式化）"
```

---

### Task 3: 事件處理核心（event_service.py）

**Files:**
- Create: `event_service.py`
- Test: `tests/test_event_service.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 models、Task 2 的 `sse.pool`
- Produces: `event_service.DeviceNotFoundError(Exception)`、`event_service.serialize_event(event: DetectEvent, device: Device) -> dict`（含 device_name/location 的完整事件 dict，detected_at 轉 ISO 字串）、`event_service.handle_incoming_event(db: Session, data: dict) -> dict`（存 DB → 廣播 event_created → 回傳序列化結果；裝置不存在丟 DeviceNotFoundError，什麼都不發生）

- [x] **Step 1: 寫失敗測試**

建立 `tests/test_event_service.py`：

```python
# 測事件處理核心：入口（POST/Kafka）共用的 handle_incoming_event()
from datetime import datetime
import pytest

from event_service import handle_incoming_event, DeviceNotFoundError
from models import DetectEvent
from sse import pool

VALID_DATA = {
    "device_id": 1,
    "event_type": "fall",
    "clip_path": "s3://clips/e1.mp4",
    "detected_at": datetime(2026, 7, 2, 14, 30),
}


def test_存DB成功並廣播event_created(db_session):
    q = pool.register()
    try:
        payload = handle_incoming_event(db_session, dict(VALID_DATA))
    finally:
        pool.unregister(q)

    # 存進 DB 了
    assert db_session.query(DetectEvent).count() == 1
    # 廣播了，且訊息裡帶完整事件（含裝置名稱，前端零額外請求）
    msg = q.get_nowait()
    assert msg["event"] == "event_created"
    assert msg["data"]["device_name"] == "交誼廳-01"
    assert msg["data"]["location"] == "交誼廳"
    assert msg["data"]["status"] == "pending"
    # 回傳值和廣播內容是同一包
    assert payload["event_id"] == msg["data"]["event_id"]


def test_裝置不存在_不存DB_不廣播(db_session):
    q = pool.register()
    try:
        with pytest.raises(DeviceNotFoundError):
            handle_incoming_event(db_session, {**VALID_DATA, "device_id": 999})
    finally:
        pool.unregister(q)

    assert db_session.query(DetectEvent).count() == 0  # 什麼都沒存
    assert q.empty()                                    # 什麼都沒廣播
```

- [x] **Step 2: 跑測試確認失敗**

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/test_event_service.py -v
```

預期：FAIL，`ModuleNotFoundError: No module named 'event_service'`

- [x] **Step 3: 實作 event_service.py**

```python
# event_service.py
# 事件「處理」核心：存 DB + 廣播。跟「入口」（POST /events、未來的 Kafka consumer）拆開，
# Kafka 接上時直接呼叫 handle_incoming_event()，這裡零改動
from sqlalchemy.orm import Session

from models import DetectEvent, Device
from sse import pool


class DeviceNotFoundError(Exception):
    # 事件指到不存在的裝置。入口層自己決定怎麼回應（HTTP 入口回 400）
    pass


def serialize_event(event: DetectEvent, device: Device) -> dict:
    # 事件的統一 JSON 結構：SSE 廣播和 GET /events 都用這一個函式，
    # 前端只需寫一套顯示邏輯。裝置名稱/位置直接夾帶，前端不用再查
    return {
        "event_id": event.event_id,
        "device_id": event.device_id,
        "device_name": device.device_name,
        # relationship 自動查 locations 表；裝置還沒定位置時回 None
        "location": device.location.location_name if device.location else None,
        "event_type": event.event_type,
        "status": event.status,
        "verdict": event.verdict,
        "clip_path": event.clip_path,
        "snapshot_path": event.snapshot_path,
        "detected_at": event.detected_at.isoformat(),
        "staff_id": event.staff_id,
        "company_id": event.company_id,
        "yolo_score": event.yolo_score,
        "yolo_threshold": event.yolo_threshold,
        "vlm_summary": event.vlm_summary,
        "severity": event.severity,
    }


def handle_incoming_event(db: Session, data: dict) -> dict:
    # 1. 先確認裝置存在（不存在就什麼都不做）
    device = db.query(Device).filter(Device.device_id == data["device_id"]).first()
    if device is None:
        raise DeviceNotFoundError(f"裝置 {data['device_id']} 不存在")

    # 2. 先存 DB（status 一律後端設 pending，company_id 跟著裝置走）
    event = DetectEvent(**data, company_id=device.company_id)
    db.add(event)
    db.commit()
    db.refresh(event)

    # 3. 存成功才廣播（資料庫是唯一真相；存失敗上面就丟例外，不會走到這行）
    payload = serialize_event(event, device)
    pool.broadcast("event_created", payload)
    return payload
```

- [x] **Step 4: 跑測試確認通過**

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/test_event_service.py -v
```

預期：2 個全 PASS

- [x] **Step 5: Commit**

```bash
git add event_service.py tests/test_event_service.py
git commit -m "feat: handle_incoming_event 事件處理核心（存 DB → 廣播，入口與處理拆開）"
```

---

### Task 4: POST /events 端點 + API Key 驗證

**Files:**
- Create: `event_routes.py`
- Modify: `main.py`（include_router）
- Test: `tests/test_events_post.py`（新建）

**Interfaces:**
- Consumes: Task 3 的 `handle_incoming_event`、`DeviceNotFoundError`
- Produces: `event_routes.router`（APIRouter，之後的任務往裡面加端點）、`event_routes.require_api_key`（Header X-API-Key 比對 `os.environ["EVENT_API_KEY"]`）、`POST /events`（201 + 事件 JSON；401 key 錯；400 裝置不存在；422 缺必填欄位）

- [x] **Step 1: 寫失敗測試**

建立 `tests/test_events_post.py`：

```python
# 測 POST /events：判斷層送事件進來的入口（機器對機器，用 API Key 驗證）
API_KEY_HEADERS = {"X-API-Key": "test-api-key"}  # conftest.py 設定的測試 key

VALID_BODY = {
    "device_id": 1,
    "event_type": "fall",
    "clip_path": "s3://clips/e1.mp4",
    "detected_at": "2026-07-02T14:30:00",
}


def test_沒帶key_401(client):
    res = client.post("/events", json=VALID_BODY)
    assert res.status_code == 401


def test_key錯誤_401(client):
    res = client.post("/events", json=VALID_BODY, headers={"X-API-Key": "wrong-key"})
    assert res.status_code == 401


def test_正常建立_201(client):
    res = client.post("/events", json=VALID_BODY, headers=API_KEY_HEADERS)
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "pending"       # 後端一律設 pending
    assert data["verdict"] is None
    assert data["device_name"] == "交誼廳-01"  # 序列化直接夾帶裝置資訊


def test_裝置不存在_400(client):
    res = client.post("/events", json={**VALID_BODY, "device_id": 999}, headers=API_KEY_HEADERS)
    assert res.status_code == 400


def test_缺必填欄位_422(client):
    body = dict(VALID_BODY)
    del body["clip_path"]  # clip_path 是必填
    res = client.post("/events", json=body, headers=API_KEY_HEADERS)
    assert res.status_code == 422
```

- [x] **Step 2: 跑測試確認失敗**

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/test_events_post.py -v
```

預期：FAIL（404，因為 /events 路由還不存在）

- [x] **Step 3: 實作 event_routes.py**

```python
# event_routes.py
# 事件相關的所有路由。用 APIRouter 分檔，main.py 保持乾淨
import os
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from event_service import handle_incoming_event, DeviceNotFoundError

router = APIRouter()


# ── 機器驗證：判斷層帶 X-API-Key，跟 .env 的 EVENT_API_KEY 比對 ──
def require_api_key(x_api_key: Optional[str] = Header(None)):
    expected = os.environ.get("EVENT_API_KEY")
    if not expected or x_api_key != expected:
        raise HTTPException(status_code=401, detail="API key 無效或未提供")


# ── POST /events 收到的 JSON 格式 ──
# 注意：沒有 status 欄位——status 一律由後端設 pending，不接受外部指定（spec 規定）
class EventCreateRequest(BaseModel):
    device_id: int
    event_type: str
    clip_path: str
    detected_at: datetime
    snapshot_path: Optional[str] = None
    yolo_score: Optional[float] = None
    yolo_threshold: Optional[float] = None
    vlm_summary: Optional[str] = None
    severity: Optional[Literal["low", "medium", "high"]] = None


# ════════════════════════════════════════════════════════
# POST /events（判斷層專用，API Key 驗證）
# ════════════════════════════════════════════════════════
# async def 的原因：廣播（put_nowait）要在事件迴圈執行緒上跑才安全
@router.post("/events", status_code=201, dependencies=[Depends(require_api_key)])
async def create_event(body: EventCreateRequest, db: Session = Depends(get_db)):
    try:
        # model_dump() 把 Pydantic 物件轉成 dict，交給共用處理函式
        return handle_incoming_event(db, body.model_dump())
    except DeviceNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

- [x] **Step 4: main.py 掛上 router**

在 `main.py` 的 import 區加：

```python
from event_routes import router as event_router
```

在 `app.add_middleware(...)` 區塊之後加：

```python
# 事件相關路由（POST /events、SSE、判定/結案）都在 event_routes.py
app.include_router(event_router)
```

- [x] **Step 5: 跑測試確認通過（全套）**

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/ -v
```

預期：全部 PASS

- [x] **Step 6: Commit**

```bash
git add event_routes.py main.py tests/test_events_post.py
git commit -m "feat: POST /events 端點 + X-API-Key 機器驗證"
```

---

### Task 5: GET /events 事件列表 + GET /staff 照護員名單

**Files:**
- Modify: `event_routes.py`（加 2 個端點）
- Test: `tests/test_events_list.py`、`tests/test_staff.py`（新建）

**Interfaces:**
- Consumes: `dependencies.get_current_user`（既有 JWT 驗證）、Task 3 的 `serialize_event`、conftest 的 `auth_headers`/`make_event`
- Produces: `GET /events`（登入即可，回傳事件陣列、detected_at 新→舊、每筆同 serialize_event 結構）、`GET /staff`（登入即可，回傳 `[{"staff_id": int, "staff_name": str}]`）

- [x] **Step 1: 寫失敗測試**

建立 `tests/test_events_list.py`：

```python
# 測 GET /events：前端進頁面時拉的事件列表（含歷史）
from datetime import datetime


def test_未登入_401(client):
    res = client.get("/events")
    assert res.status_code == 401


def test_列表依偵測時間新到舊(client, auth_headers, make_event):
    make_event(detected_at=datetime(2026, 7, 1, 10, 0))   # 舊
    make_event(detected_at=datetime(2026, 7, 2, 15, 0))   # 新

    res = client.get("/events", headers=auth_headers)
    assert res.status_code == 200
    events = res.json()
    assert len(events) == 2
    assert events[0]["detected_at"] > events[1]["detected_at"]  # 新的排前面


def test_列表帶裝置名稱(client, auth_headers, make_event):
    make_event()
    res = client.get("/events", headers=auth_headers)
    assert res.json()[0]["device_name"] == "交誼廳-01"
    assert res.json()[0]["location"] == "交誼廳"
```

建立 `tests/test_staff.py`：

```python
# 測 GET /staff：前端「指派照護員」下拉選單的資料來源


def test_未登入_401(client):
    res = client.get("/staff")
    assert res.status_code == 401


def test_回傳照護員名單(client, auth_headers):
    res = client.get("/staff", headers=auth_headers)
    assert res.status_code == 200
    names = [s["staff_name"] for s in res.json()]
    assert names == ["小美", "阿強"]  # conftest 種子資料
```

- [x] **Step 2: 跑測試確認失敗**

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/test_events_list.py tests/test_staff.py -v
```

預期：FAIL（404，路由不存在）

- [x] **Step 3: 實作兩個端點**

`event_routes.py` 的 import 區補：

```python
from dependencies import get_current_user
from event_service import serialize_event
from models import DetectEvent, Device, Staff
```

檔案末尾加：

```python
# ════════════════════════════════════════════════════════
# GET /events（登入即可）：事件列表，新到舊
# ════════════════════════════════════════════════════════
@router.get("/events")
def list_events(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # JOIN 裝置表，一次查好裝置名稱/位置，跟 SSE 廣播用同一個序列化函式
    rows = (
        db.query(DetectEvent, Device)
        .join(Device, DetectEvent.device_id == Device.device_id)
        .order_by(DetectEvent.detected_at.desc())
        .all()
    )
    return [serialize_event(event, device) for event, device in rows]


# ════════════════════════════════════════════════════════
# GET /staff（登入即可）：照護員名單（指派下拉選單用）
# ════════════════════════════════════════════════════════
@router.get("/staff")
def list_staff(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return [
        {"staff_id": s.staff_id, "staff_name": s.staff_name}
        for s in db.query(Staff).order_by(Staff.staff_id).all()
    ]
```

- [x] **Step 4: 跑測試確認通過（全套）**

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/ -v
```

預期：全部 PASS

- [x] **Step 5: Commit**

```bash
git add event_routes.py tests/test_events_list.py tests/test_staff.py
git commit -m "feat: GET /events 事件列表 + GET /staff 照護員名單"
```

---

### Task 6: PATCH /events/{id}/verdict 人工判定

**Files:**
- Modify: `event_routes.py`（加 1 個端點）
- Test: `tests/test_verdict.py`（新建）

**Interfaces:**
- Consumes: Task 1-5 全部；conftest 的 `make_event`（可指定 status/verdict 造出任意狀態的事件）
- Produces: `PATCH /events/{event_id}/verdict`，body `{"verdict": "true_alarm"|"false_alarm", "staff_id": int|null}`。狀態轉換：pending+誤報→resolved；pending+真跌倒（必帶 staff_id）→in_progress。錯誤：404 不存在、409 非 pending、422 真跌倒沒帶 staff_id、400 staff_id 不存在。成功後廣播 `event_updated`

- [x] **Step 1: 寫失敗測試**

建立 `tests/test_verdict.py`：

```python
# 測 PATCH /events/{id}/verdict：值班人員判定真跌倒/誤報
# 狀態轉換規則（spec 第 3 節）只寫在後端，這裡逐條驗證
from sse import pool


def test_未登入_401(client, make_event):
    event = make_event()
    res = client.patch(f"/events/{event.event_id}/verdict", json={"verdict": "false_alarm"})
    assert res.status_code == 401


def test_判誤報_直接結案(client, auth_headers, make_event):
    event = make_event()  # 預設 status=pending

    res = client.patch(
        f"/events/{event.event_id}/verdict",
        json={"verdict": "false_alarm"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "resolved"      # 誤報不用派人，直接結案
    assert data["verdict"] == "false_alarm"
    assert data["staff_id"] is None


def test_判真跌倒_進入處理中並指派照護員(client, auth_headers, make_event):
    event = make_event()

    res = client.patch(
        f"/events/{event.event_id}/verdict",
        json={"verdict": "true_alarm", "staff_id": 2},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "in_progress"
    assert data["verdict"] == "true_alarm"
    assert data["staff_id"] == 2


def test_判真跌倒沒帶照護員_422(client, auth_headers, make_event):
    event = make_event()
    res = client.patch(
        f"/events/{event.event_id}/verdict",
        json={"verdict": "true_alarm"},
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_照護員不存在_400(client, auth_headers, make_event):
    event = make_event()
    res = client.patch(
        f"/events/{event.event_id}/verdict",
        json={"verdict": "true_alarm", "staff_id": 999},
        headers=auth_headers,
    )
    assert res.status_code == 400


def test_已判定過再判_409(client, auth_headers, make_event):
    # 造一筆已經判定過的事件（另一個值班人員搶先處理了）
    event = make_event(status="in_progress", verdict="true_alarm", staff_id=1)
    res = client.patch(
        f"/events/{event.event_id}/verdict",
        json={"verdict": "false_alarm"},
        headers=auth_headers,
    )
    assert res.status_code == 409


def test_事件不存在_404(client, auth_headers):
    res = client.patch(
        "/events/00000000-0000-0000-0000-000000000000/verdict",
        json={"verdict": "false_alarm"},
        headers=auth_headers,
    )
    assert res.status_code == 404


def test_判定成功會廣播event_updated(client, auth_headers, make_event):
    event = make_event()
    q = pool.register()
    try:
        client.patch(
            f"/events/{event.event_id}/verdict",
            json={"verdict": "false_alarm"},
            headers=auth_headers,
        )
    finally:
        pool.unregister(q)

    msg = q.get_nowait()
    assert msg["event"] == "event_updated"
    assert msg["data"]["status"] == "resolved"
```

- [x] **Step 2: 跑測試確認失敗**

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/test_verdict.py -v
```

預期：FAIL（405 或 404，路由不存在）

- [x] **Step 3: 實作 verdict 端點**

`event_routes.py` 的 import 區補（sse 的 pool）：

```python
from sse import pool
```

檔案末尾加：

```python
# ── PATCH /events/{id}/verdict 收到的 JSON 格式 ──
class VerdictRequest(BaseModel):
    verdict: Literal["true_alarm", "false_alarm"]
    staff_id: Optional[int] = None  # 只有判真跌倒時必填


# ════════════════════════════════════════════════════════
# PATCH /events/{event_id}/verdict（登入即可）：人工判定
# ════════════════════════════════════════════════════════
@router.patch("/events/{event_id}/verdict")
async def verdict_event(
    event_id: str,
    body: VerdictRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = db.query(DetectEvent).filter(DetectEvent.event_id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="事件不存在")

    # 狀態轉換守門：只有 pending 能被判定（409 = 請求沒錯，但跟目前狀態衝突）
    if event.status != "pending":
        raise HTTPException(status_code=409, detail="事件已被判定過")

    if body.verdict == "true_alarm":
        # 真跌倒：必須同時指派照護員
        if body.staff_id is None:
            raise HTTPException(status_code=422, detail="判定真跌倒必須指派照護員（staff_id）")
        staff = db.query(Staff).filter(Staff.staff_id == body.staff_id).first()
        if staff is None:
            raise HTTPException(status_code=400, detail=f"照護員 {body.staff_id} 不存在")
        event.status = "in_progress"
        event.verdict = "true_alarm"
        event.staff_id = body.staff_id
    else:
        # 誤報：不用派人，直接結案（staff_id 留空）
        event.status = "resolved"
        event.verdict = "false_alarm"

    db.commit()
    db.refresh(event)

    # 先存後播：commit 成功才廣播，讓所有中控站畫面同步
    device = db.query(Device).filter(Device.device_id == event.device_id).first()
    payload = serialize_event(event, device)
    pool.broadcast("event_updated", payload)
    return payload
```

- [x] **Step 4: 跑測試確認通過（全套）**

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/ -v
```

預期：全部 PASS

- [x] **Step 5: Commit**

```bash
git add event_routes.py tests/test_verdict.py
git commit -m "feat: PATCH /events/{id}/verdict 人工判定（含狀態轉換守門與廣播）"
```

---

### Task 7: PATCH /events/{id}/resolve 結案

**Files:**
- Modify: `event_routes.py`（加 1 個端點）
- Test: `tests/test_resolve.py`（新建）

**Interfaces:**
- Consumes: Task 6 為止的全部
- Produces: `PATCH /events/{event_id}/resolve`（無 body）。只有 `in_progress` 能結案 → `resolved`；404 不存在、409 狀態不對。成功後廣播 `event_updated`

- [x] **Step 1: 寫失敗測試**

建立 `tests/test_resolve.py`：

```python
# 測 PATCH /events/{id}/resolve：照護員處理完，值班人員標記結案
from sse import pool


def test_未登入_401(client, make_event):
    event = make_event(status="in_progress", verdict="true_alarm", staff_id=1)
    res = client.patch(f"/events/{event.event_id}/resolve")
    assert res.status_code == 401


def test_處理中的事件可以結案(client, auth_headers, make_event):
    event = make_event(status="in_progress", verdict="true_alarm", staff_id=1)

    res = client.patch(f"/events/{event.event_id}/resolve", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "resolved"
    assert data["verdict"] == "true_alarm"  # 判定結果不變，只改進度


def test_還沒判定就結案_409(client, auth_headers, make_event):
    event = make_event()  # status=pending
    res = client.patch(f"/events/{event.event_id}/resolve", headers=auth_headers)
    assert res.status_code == 409


def test_已結案再結案_409(client, auth_headers, make_event):
    event = make_event(status="resolved", verdict="false_alarm")
    res = client.patch(f"/events/{event.event_id}/resolve", headers=auth_headers)
    assert res.status_code == 409


def test_事件不存在_404(client, auth_headers):
    res = client.patch(
        "/events/00000000-0000-0000-0000-000000000000/resolve",
        headers=auth_headers,
    )
    assert res.status_code == 404


def test_結案成功會廣播event_updated(client, auth_headers, make_event):
    event = make_event(status="in_progress", verdict="true_alarm", staff_id=1)
    q = pool.register()
    try:
        client.patch(f"/events/{event.event_id}/resolve", headers=auth_headers)
    finally:
        pool.unregister(q)

    msg = q.get_nowait()
    assert msg["event"] == "event_updated"
    assert msg["data"]["status"] == "resolved"
```

- [x] **Step 2: 跑測試確認失敗**

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/test_resolve.py -v
```

預期：FAIL（405 或 404，路由不存在）

- [x] **Step 3: 實作 resolve 端點**

`event_routes.py` 檔案末尾加：

```python
# ════════════════════════════════════════════════════════
# PATCH /events/{event_id}/resolve（登入即可）：結案
# ════════════════════════════════════════════════════════
@router.patch("/events/{event_id}/resolve")
async def resolve_event(
    event_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = db.query(DetectEvent).filter(DetectEvent.event_id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="事件不存在")

    # 只有「處理中」能結案：pending 還沒判定、resolved 已經結過了
    if event.status != "in_progress":
        raise HTTPException(status_code=409, detail="只有處理中的事件可以結案")

    event.status = "resolved"
    db.commit()
    db.refresh(event)

    device = db.query(Device).filter(Device.device_id == event.device_id).first()
    payload = serialize_event(event, device)
    pool.broadcast("event_updated", payload)
    return payload
```

- [x] **Step 4: 跑測試確認通過（全套）**

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/ -v
```

預期：全部 PASS

- [x] **Step 5: Commit**

```bash
git add event_routes.py tests/test_resolve.py
git commit -m "feat: PATCH /events/{id}/resolve 結案端點"
```

---

### Task 8: GET /stream SSE 長連線端點

**Files:**
- Modify: `event_routes.py`（加 token 驗證依賴 + 1 個端點）
- Modify: `tests/test_sse.py`（加端點驗證測試）

**Interfaces:**
- Consumes: `auth.decode_access_token`（既有）、Task 2 的 `pool`/`format_sse`
- Produces: `event_routes.get_user_from_query_token(token: str|None Query) -> dict`（401 無效/沒帶）、`GET /stream?token=`（text/event-stream 長連線，15 秒心跳 `: ping`，斷線自動 unregister）

- [x] **Step 1: 寫失敗測試**

在 `tests/test_sse.py` 末尾加：

```python
# ── /stream 端點的驗證測試 ──
# 長連線本身難在測試裡「等」，所以只考驗證擋不擋；
# 廣播邏輯上面已經直接考過連線池了
from event_routes import get_user_from_query_token
import pytest
from fastapi import HTTPException


def test_stream_沒帶token_401(client):
    res = client.get("/stream")
    assert res.status_code == 401


def test_stream_token亂寫_401(client):
    res = client.get("/stream", params={"token": "not-a-real-token"})
    assert res.status_code == 401


def test_query_token_合法token驗證通過(staff_token):
    # 直接測依賴函式：合法 token 解得出使用者資料
    payload = get_user_from_query_token(token=staff_token)
    assert payload["sub"] == "alice"


def test_query_token_無效token丟401():
    with pytest.raises(HTTPException) as exc:
        get_user_from_query_token(token="bad-token")
    assert exc.value.status_code == 401
```

- [x] **Step 2: 跑測試確認失敗**

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/test_sse.py -v
```

預期：FAIL，`ImportError: cannot import name 'get_user_from_query_token'`

- [x] **Step 3: 實作 /stream 端點**

`event_routes.py` 的 import 區補：

```python
import asyncio

from fastapi import Query
from fastapi.responses import StreamingResponse

from auth import decode_access_token
from sse import format_sse
```

檔案末尾加：

```python
# ── SSE 專用驗證：EventSource 不能自訂 header，token 改放網址參數 ──
# 同一張 JWT，只是改插的位置；驗證邏輯用同一個 decode_access_token
def get_user_from_query_token(token: Optional[str] = Query(None)):
    if token is None:
        raise HTTPException(status_code=401, detail="缺少 token")
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="token 無效或過期")
    return payload


# ════════════════════════════════════════════════════════
# GET /stream（登入即可，token 放 query）：SSE 長連線
# ════════════════════════════════════════════════════════
@router.get("/stream")
async def stream(current_user: dict = Depends(get_user_from_query_token)):
    q = pool.register()  # 進來就掛一個信箱到連線池

    async def event_generator():
        try:
            while True:
                try:
                    # 守在自己的信箱旁等訊息，最多等 15 秒
                    message = await asyncio.wait_for(q.get(), timeout=15)
                    yield format_sse(message)
                except asyncio.TimeoutError:
                    # 15 秒沒事件 → 送心跳，防止中間網路設備掐斷「太久沒動靜」的連線
                    yield ": ping\n\n"
        finally:
            # 瀏覽器關掉/斷線/F5 → generator 被取消 → 把信箱移出連線池
            pool.unregister(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

- [x] **Step 4: 跑測試確認通過（全套）**

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/ -v
```

預期：全部 PASS

- [x] **Step 5: 手動煙霧測試（真的開一條 SSE 連線看看）**

啟動服務：

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m uvicorn main:app --reload
```

另開一個終端機，先登入拿 token，再連 /stream（會掛著不動，15 秒看到 `: ping` 就成功）：

```powershell
$login = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/login -Body @{username="admin"; password="123456"}
curl.exe -N "http://127.0.0.1:8000/stream?token=$($login.access_token)"
```

預期：連線保持開啟，約每 15 秒出現一行 `: ping`。確認後 Ctrl+C 結束。

- [x] **Step 6: Commit**

```bash
git add event_routes.py tests/test_sse.py
git commit -m "feat: GET /stream SSE 長連線（query token 驗證 + 15 秒心跳）"
```

---

### Task 9: 種子資料腳本 + PostgreSQL 遷移腳本 + .env 範本

**Files:**
- Create: `create_seed_data.py`
- Create: `migrate_add_company_id.py`
- Modify: `.env.example`（加 EVENT_API_KEY）

**Interfaces:**
- Consumes: `database.SessionLocal`/`engine`/`Base`、Task 1 的 models
- Produces: 對正式 PostgreSQL 的一次性初始化能力（建表 + 種子 + user_account 加欄位）。腳本可重複執行不報錯（已有資料自動略過，跟 create_test_user.py 同風格）

- [x] **Step 1: 寫 create_seed_data.py**

```python
# create_seed_data.py
# 對正式 PostgreSQL 建新表 + 種初始資料：預設公司、示範裝置、照護員
# 可重複執行：已有資料自動略過，不會報錯（跟 create_test_user.py 同風格）
from database import SessionLocal, Base, engine
import models  # noqa: F401  讓 Base 認得所有表，create_all 才會建

Base.metadata.create_all(bind=engine)  # 建立還不存在的表（已存在的不動）

from models import Company, Location, Device, Staff  # noqa: E402

db = SessionLocal()

if db.query(Company).filter_by(company_id=1).first() is None:
    db.add(Company(company_id=1, company_name="扶力憐示範安養院"))
    db.commit()
    print("已建立預設公司（id=1）")
else:
    print("預設公司已存在，略過")

if db.query(Location).first() is None:
    db.add(Location(location_name="交誼廳", company_id=1))
    db.add(Location(location_name="走廊", company_id=1))
    db.commit()
    print("已建立區域 2 筆")
else:
    print("區域已存在，略過")

if db.query(Device).first() is None:
    # 查出剛種的區域編號，裝置掛上對應的 location_id
    loc_ids = {l.location_name: l.location_id for l in db.query(Location).all()}
    db.add(Device(device_name="交誼廳-01", location_id=loc_ids.get("交誼廳"), status="active", company_id=1))
    db.add(Device(device_name="走廊-01", location_id=loc_ids.get("走廊"), status="active", company_id=1))
    db.commit()
    print("已建立示範裝置 2 台")
else:
    print("裝置已存在，略過")

if db.query(Staff).first() is None:
    db.add(Staff(staff_name="照護員A", company_id=1))
    db.add(Staff(staff_name="照護員B", company_id=1))
    db.commit()
    print("已建立照護員 2 名")
else:
    print("照護員已存在，略過")

db.close()
print("種子資料完成")
```

- [x] **Step 2: 寫 migrate_add_company_id.py**

```python
# migrate_add_company_id.py
# 一次性遷移：幫既有的 user_account 表加 company_id 欄位
# NOT NULL DEFAULT 1 → PostgreSQL 加欄位的當下，舊帳號自動回填 1（預設公司）
# 可重複執行：IF NOT EXISTS 讓第二次跑直接略過
from sqlalchemy import text
from database import engine

with engine.begin() as conn:
    conn.execute(text(
        "ALTER TABLE user_account "
        "ADD COLUMN IF NOT EXISTS company_id INT NOT NULL DEFAULT 1"
    ))

print("user_account.company_id 遷移完成（已存在則略過）")
```

- [x] **Step 3: 更新 .env.example**

在 `.env.example` 末尾加：

```
# 判斷層呼叫 POST /events 用的機器驗證 key（請換成隨機長字串）
EVENT_API_KEY=change-me-to-a-long-random-string
```

同時提醒使用者在自己的 `.env` 加上真實的 `EVENT_API_KEY`（產生方式：`python -c "import secrets; print(secrets.token_urlsafe(32))"`）。

- [x] **Step 4: 對正式 PostgreSQL 執行（需使用者在場確認）**

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" create_seed_data.py
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" migrate_add_company_id.py
```

預期輸出：各步驟的「已建立…」訊息；第二次執行全部顯示「略過」。

- [x] **Step 5: 跑全套測試確認沒壞**

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/ -v
```

預期：全部 PASS

- [x] **Step 6: Commit**

```bash
git add create_seed_data.py migrate_add_company_id.py .env.example
git commit -m "feat: 種子資料腳本 + user_account 遷移腳本 + EVENT_API_KEY 範本"
```

---

### Task 10: 文件更新 + 最終驗收

**Files:**
- Modify: `CLAUDE.md`（API 表加 6 個端點改成「已實作」、檔案結構加新檔案）
- Modify: `docs/event-sse-discussion-handoff.md`（頂部加「已完成實作」註記）

- [x] **Step 1: 更新 CLAUDE.md**

「API 路由」表格加 6 列（並刪掉「已完成設計、尚未實作」那段話）：

```markdown
| POST   | `/events`     | X-API-Key | 判斷層送入新事件（status=pending），存 DB 後 SSE 廣播 |
| GET    | `/stream`     | 需登入（token 放 query 參數） | SSE 長連線，推播 event_created / event_updated |
| GET    | `/events`     | 需登入   | 事件列表（新→舊，含裝置名稱/位置）    |
| GET    | `/staff`      | 需登入   | 照護員名單（指派下拉選單用）          |
| PATCH  | `/events/{id}/verdict` | 需登入 | 判定：誤報→直接結案；真跌倒（必帶 staff_id）→處理中 |
| PATCH  | `/events/{id}/resolve` | 需登入 | 結案（僅限處理中的事件）              |
```

「檔案結構」表格加：

```markdown
| `sse.py`              | SSE 連線池（register/unregister/broadcast）        |
| `event_service.py`    | 事件處理核心：handle_incoming_event（存 DB → 廣播）|
| `event_routes.py`     | 事件相關 6 個端點（APIRouter）                     |
| `create_seed_data.py` | 種子資料腳本（公司/裝置/照護員，可重複執行）       |
| `migrate_add_company_id.py` | user_account 加 company_id 的一次性遷移      |
```

「資料庫」段落的「規劃中」改成「已建立」，並在專案概述把「**進行中**」段落改成已完成。

- [x] **Step 2: 在 handoff 文件頂部加註記**

`docs/event-sse-discussion-handoff.md` 第 3 行（引言區）加：

```markdown
> ✅ **此功能已完成實作**（2026-07）。本文件保留作討論過程紀錄；
> 最終設計以 `docs/superpowers/specs/2026-07-02-event-sse-design.md` 為準。
```

- [x] **Step 3: 最終全套測試**

```powershell
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/ -v
```

預期：全部 PASS（既有 16 + 新增約 30 個）

- [x] **Step 4: 手動端到端驗收（模擬完整流程）**

啟動服務後，依序：

```powershell
# 1. 登入
$login = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/login -Body @{username="admin"; password="123456"}
$headers = @{Authorization = "Bearer $($login.access_token)"}

# 2. 判斷層送一筆事件（EVENT_API_KEY 換成 .env 裡的真實值）
$eventBody = '{"device_id": 1, "event_type": "fall", "clip_path": "s3://clips/demo.mp4", "detected_at": "2026-07-02T14:30:00", "severity": "high"}'
$created = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/events -Body $eventBody -ContentType "application/json" -Headers @{"X-API-Key" = "你的EVENT_API_KEY"}

# 3. 查列表看得到
Invoke-RestMethod -Uri http://127.0.0.1:8000/events -Headers $headers

# 4. 判定真跌倒 + 指派照護員
$verdictBody = '{"verdict": "true_alarm", "staff_id": 1}'
Invoke-RestMethod -Method Patch -Uri "http://127.0.0.1:8000/events/$($created.event_id)/verdict" -Body $verdictBody -ContentType "application/json" -Headers $headers

# 5. 結案
Invoke-RestMethod -Method Patch -Uri "http://127.0.0.1:8000/events/$($created.event_id)/resolve" -Headers $headers
```

預期：步驟 2 回 201、步驟 4 回 status=in_progress、步驟 5 回 status=resolved。
（若同時開著 Task 8 的 `curl.exe -N` 連線，每一步都會看到即時推播。）

- [x] **Step 5: Commit**

```bash
git add CLAUDE.md docs/event-sse-discussion-handoff.md
git commit -m "docs: 事件通報 + SSE 功能完成，更新 CLAUDE.md 與交接文件"
```

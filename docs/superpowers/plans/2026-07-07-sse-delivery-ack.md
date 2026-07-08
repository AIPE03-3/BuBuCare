# SSE 送達確認 + 重推保護 Implementation Plan

> **執行方式：** 用 superpowers:executing-plans 逐任務實作。步驟用 checkbox（`- [ ]`）追蹤。

**Goal:** 事件 SSE 推播後，前端自動回報收到；後端沒收到 ack 就自動重推同一筆，最多 3 次，降低漏接風險。

**Architecture:** 新增 `detect_events.notified_at` 時間戳當「已收到」的章；新增 `POST /events/{id}/ack` 讓前端蓋章；`POST /events` 建立事件後由路由層啟動一個 asyncio 背景任務，每 10 秒檢查一次是否已送達（ack 到 / 有人處理），沒有就重推 `event_created`。

**Tech Stack:** FastAPI、SQLAlchemy、asyncio（不加新套件）、pytest（同步測試 + `asyncio.run` 驅動背景任務）。

## Global Constraints

- Python 3.12；不新增第三方套件（計時器用內建 asyncio）
- 測試指令（PowerShell 全新 session）：`& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest <路徑> -v`
- 不動 `status` / `verdict` 的 ENUM 值；`notified_at` 是獨立軸，不塞進 status
- 重推沿用 `event_created` 事件名，不另發新名（前端以 `event_id` 去重）
- 背景任務的「啟動」放路由層 `create_event`，不放進同步的 `handle_incoming_event`（後者被測試直接呼叫、無 event loop，內部 `create_task` 會爆 `RuntimeError`）
- 背景任務只在單一程序有效；多 worker 的限制記入 `docs/future-work.md`

---

### Task 1: `notified_at` 欄位 + 序列化

**Files:**

- Modify: `models.py`（DetectEvent 加欄位）
- Modify: `event_service.py:15-36`（serialize_event 加一鍵）
- Test: `tests/test_event_service.py`

**Interfaces:**

- Produces: `DetectEvent.notified_at`（`Optional[datetime]`, nullable）；`serialize_event(event, device)` 回傳 dict 多一鍵 `notified_at`（ISO 字串或 None）

- [ ] **Step 1: Write the failing test**

在 `tests/test_event_service.py` 末尾加：

```python
def test_serialize包含notified_at預設None(db_session, make_event):
    from models import Device
    event = make_event()
    device = db_session.query(Device).filter(Device.device_id == 1).first()
    data = serialize_event(event, device)
    assert "notified_at" in data
    assert data["notified_at"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/test_event_service.py::test_serialize包含notified_at預設None -v`
Expected: FAIL with `KeyError: 'notified_at'`（或 `"notified_at" in data` 斷言失敗）

- [ ] **Step 3: Write minimal implementation**

`models.py` 的 `DetectEvent`，在 `detected_at` 那行下面加：

```python
    # 前端第一次回報收到（ack）的時間；NULL = 尚未收到，重推機制據此判斷要不要補推
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
```

`event_service.py` 的 `serialize_event` 回傳 dict，在 `"detected_at": ...` 之後加一行：

```python
        # 讓前端/除錯看得到送達狀態：None = 還沒被 ack
        "notified_at": event.notified_at.isoformat() if event.notified_at else None,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/test_event_service.py -v`
Expected: PASS（含既有測試全過）

- [ ] **Step 5: 正式環境備註（不執行、僅記錄）**

正式 PostgreSQL 已有 `detect_events` 資料表，部署時需手動補欄位（測試用 SQLite 每次 `create_all` 不受影響）：

```sql
ALTER TABLE detect_events ADD COLUMN notified_at TIMESTAMP;
```

- [ ] **Step 6: Commit**

```bash
git add models.py event_service.py tests/test_event_service.py
git commit -m "feat: detect_events 加 notified_at 欄位 + serialize 暴露"
```

---

### Task 2: `is_delivered` 送達判斷純函式

**Files:**

- Modify: `event_service.py`（新增函式）
- Test: `tests/test_delivery.py`（新檔）

**Interfaces:**

- Consumes: `DetectEvent.notified_at`（Task 1）
- Produces: `is_delivered(db: Session, event_id: str) -> bool`——True = 可停止重推（已 ack / 已被處理 / 事件不存在）

- [ ] **Step 1: Write the failing test**

新檔 `tests/test_delivery.py`：

```python
# 測送達判斷 + 重推邏輯
from datetime import datetime

from event_service import is_delivered


def test_is_delivered_notified有值即已送達(db_session, make_event):
    event = make_event(notified_at=datetime(2026, 7, 2, 14, 31))
    assert is_delivered(db_session, event.event_id) is True


def test_is_delivered_status非pending即已送達(db_session, make_event):
    event = make_event(status="in_progress", verdict="true_alarm", staff_id=1)
    assert is_delivered(db_session, event.event_id) is True


def test_is_delivered_pending且未notified為未送達(db_session, make_event):
    event = make_event()  # 預設 pending、notified_at None
    assert is_delivered(db_session, event.event_id) is False


def test_is_delivered_事件不存在視為已送達不重推(db_session):
    assert is_delivered(db_session, "no-such-id") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/test_delivery.py -v`
Expected: FAIL with `ImportError: cannot import name 'is_delivered'`

- [ ] **Step 3: Write minimal implementation**

`event_service.py` 新增（放在 `serialize_event` 之後）：

```python
def is_delivered(db: Session, event_id: str) -> bool:
    # 重推的停止判斷。三種情況都算「不用再推」：
    #   1. notified_at 有值 → 前端已回報收到
    #   2. status 離開 pending → 有人已在處理，等於也送達了
    #   3. 事件不存在 → 已被刪或查無，沒東西可推
    event = db.query(DetectEvent).filter(DetectEvent.event_id == event_id).first()
    if event is None:
        return True
    if event.notified_at is not None:
        return True
    if event.status != "pending":
        return True
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/test_delivery.py -v`
Expected: PASS（4 個測試）

- [ ] **Step 5: Commit**

```bash
git add event_service.py tests/test_delivery.py
git commit -m "feat: is_delivered 送達判斷純函式"
```

---

### Task 3: `POST /events/{event_id}/ack` 端點

**Files:**

- Modify: `event_routes.py`（在 `POST /events` 之後新增路由；`datetime` 已 import）
- Test: `tests/test_ack.py`（新檔）

**Interfaces:**

- Produces: `POST /events/{event_id}/ack`（需登入）→ 200 + `{"status": "ok"}`；事件不存在 → 404
- 送達狀態只記在後端 DB（notified_at）給重推計時器用；ack 回最小確認，不回事件內容

- [ ] **Step 1: Write the failing test**

新檔 `tests/test_ack.py`：

```python
# 測 POST /events/{id}/ack：前端自動回報收到
from datetime import datetime

from models import DetectEvent


def test_未登入_401(client, make_event):
    event = make_event()
    res = client.post(f"/events/{event.event_id}/ack")
    assert res.status_code == 401


def test_ack成功蓋章並回200(client, auth_headers, make_event, db_session):
    event = make_event()
    assert event.notified_at is None
    res = client.post(f"/events/{event.event_id}/ack", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    db_session.expire_all()
    updated = db_session.query(DetectEvent).filter_by(event_id=event.event_id).first()
    assert updated.notified_at is not None


def test_重複ack保留第一次時間(client, auth_headers, make_event, db_session):
    first = datetime(2026, 7, 2, 14, 31)
    event = make_event(notified_at=first)
    res = client.post(f"/events/{event.event_id}/ack", headers=auth_headers)
    assert res.status_code == 200
    db_session.expire_all()
    updated = db_session.query(DetectEvent).filter_by(event_id=event.event_id).first()
    assert updated.notified_at == first


def test_事件不存在_404(client, auth_headers):
    res = client.post("/events/no-such-id/ack", headers=auth_headers)
    assert res.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/test_ack.py -v`
Expected: FAIL（找不到路由，ack 成功案例非 200）

- [ ] **Step 3: Write minimal implementation**

`event_routes.py`，緊接在 `POST /events`（`create_event`）之後新增（放在傳輸這條線，跟人工判定的 verdict/resolve 分開）：

```python
# ════════════════════════════════════════════════════════
# POST /events/{event_id}/ack（登入即可）：前端收到 SSE 後自動回報收到
# ════════════════════════════════════════════════════════
@router.post("/events/{event_id}/ack")
def ack_event(
    event_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = db.query(DetectEvent).filter(DetectEvent.event_id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="事件不存在")

    # 只蓋第一次：已有值就不動，保留最早的送達時間（重推可能觸發多次 ack）
    # 送達狀態記在後端 DB，給重推計時器判斷用（整套推送→ack→重推是 at-least-once 保證送達）
    # 前端打完 ack 不需要處理回應，回個小確認即可
    if event.notified_at is None:
        event.notified_at = datetime.now()
        db.commit()

    return {"status": "ok"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/test_ack.py -v`
Expected: PASS（4 個測試）

- [ ] **Step 5: Commit**

```bash
git add event_routes.py tests/test_ack.py
git commit -m "feat: POST /events/{id}/ack 前端送達回報端點"
```

---

### Task 4: `rebroadcast_event` 重推 helper

**Files:**

- Modify: `event_service.py`（新增函式）
- Test: `tests/test_delivery.py`

**Interfaces:**

- Consumes: `serialize_event`、`pool.broadcast`
- Produces: `rebroadcast_event(db: Session, event_id: str) -> None`——重查事件+裝置並 `broadcast("event_created", ...)`；事件不存在則不廣播

- [ ] **Step 1: Write the failing test**

在 `tests/test_delivery.py` 末尾加：

```python
def test_rebroadcast_廣播同一筆event_created(db_session, make_event):
    from event_service import rebroadcast_event
    from sse import pool
    event = make_event()
    q = pool.register()
    try:
        rebroadcast_event(db_session, event.event_id)
        msg = q.get_nowait()
        assert msg["event"] == "event_created"
        assert msg["data"]["event_id"] == event.event_id
    finally:
        pool.unregister(q)


def test_rebroadcast_事件不存在_不廣播(db_session):
    from event_service import rebroadcast_event
    from sse import pool
    q = pool.register()
    try:
        rebroadcast_event(db_session, "no-such-id")
        assert q.empty()
    finally:
        pool.unregister(q)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/test_delivery.py -v`
Expected: FAIL with `ImportError: cannot import name 'rebroadcast_event'`

- [ ] **Step 3: Write minimal implementation**

`event_service.py` 新增（放在 `is_delivered` 之後）：

```python
def rebroadcast_event(db: Session, event_id: str) -> None:
    # 重推：重查事件與裝置，沿用 event_created 事件名再廣播一次
    # （前端以 event_id 去重，收到同一筆只會更新該列、不會重複顯示）
    event = db.query(DetectEvent).filter(DetectEvent.event_id == event_id).first()
    if event is None:
        return
    device = db.query(Device).filter(Device.device_id == event.device_id).first()
    pool.broadcast("event_created", serialize_event(event, device))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/test_delivery.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add event_service.py tests/test_delivery.py
git commit -m "feat: rebroadcast_event 重推 helper"
```

---

### Task 5: `watch_delivery` 背景任務 + 接進 POST /events

**Files:**

- Modify: `event_service.py`（新增 async 函式 + import asyncio / SessionLocal）
- Modify: `event_routes.py:48-54`（create_event 建立後啟動背景任務）
- Modify: `tests/conftest.py`（新增 `session_factory` fixture）
- Modify: `docs/future-work.md`（多 worker 限制備註）
- Test: `tests/test_delivery.py`

**Interfaces:**

- Consumes: `is_delivered`（Task 2）、`rebroadcast_event`（Task 4）、`database.SessionLocal`
- Produces: `async watch_delivery(event_id: str, *, session_factory=SessionLocal, interval: float = 10.0, max_attempts: int = 3) -> None`

- [ ] **Step 1: 加 conftest fixture**

`tests/conftest.py` 末尾加：

```python
@pytest.fixture
def session_factory():
    # 背景任務測試用：回傳測試記憶體 DB 的 session 工廠
    # （watch_delivery 會用它開自己的 session，不能連到正式 DB）
    return TestingSessionLocal
```

- [ ] **Step 2: Write the failing test**

在 `tests/test_delivery.py` 末尾加（interval=0 讓 3 輪瞬間跑完，不用真的等 10 秒）：

```python
def test_watch_delivery_未ack_重推到上限(make_event, session_factory):
    import asyncio
    from event_service import watch_delivery
    from sse import pool
    event = make_event()  # pending、notified_at None
    q = pool.register()
    try:
        asyncio.run(watch_delivery(
            event.event_id, session_factory=session_factory, interval=0, max_attempts=3
        ))
        count = 0
        while not q.empty():
            assert q.get_nowait()["event"] == "event_created"
            count += 1
        assert count == 3
    finally:
        pool.unregister(q)


def test_watch_delivery_已ack_不重推(make_event, session_factory):
    import asyncio
    from datetime import datetime
    from event_service import watch_delivery
    from sse import pool
    event = make_event(notified_at=datetime(2026, 7, 2, 14, 31))
    q = pool.register()
    try:
        asyncio.run(watch_delivery(
            event.event_id, session_factory=session_factory, interval=0, max_attempts=3
        ))
        assert q.empty()
    finally:
        pool.unregister(q)


def test_watch_delivery_已被處理_不重推(make_event, session_factory):
    import asyncio
    from event_service import watch_delivery
    from sse import pool
    event = make_event(status="in_progress", verdict="true_alarm", staff_id=1)
    q = pool.register()
    try:
        asyncio.run(watch_delivery(
            event.event_id, session_factory=session_factory, interval=0, max_attempts=3
        ))
        assert q.empty()
    finally:
        pool.unregister(q)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/test_delivery.py -v`
Expected: FAIL with `ImportError: cannot import name 'watch_delivery'`

- [ ] **Step 4: Write minimal implementation**

`event_service.py` 頂部 import 區加：

```python
import asyncio

from database import SessionLocal
```

`event_service.py` 新增（放在 `rebroadcast_event` 之後）：

```python
async def watch_delivery(
    event_id: str,
    *,
    session_factory=SessionLocal,
    interval: float = 10.0,
    max_attempts: int = 3,
) -> None:
    # 事件建立後盯送達：每 interval 秒檢查一次，未送達就重推一次，最多 max_attempts 次
    # session_factory 可注入：正式用 SessionLocal，測試傳測試 DB 的工廠
    for _ in range(max_attempts):
        await asyncio.sleep(interval)
        db = session_factory()  # 背景任務不在請求裡，要開自己的 session
        try:
            if is_delivered(db, event_id):
                return
            rebroadcast_event(db, event_id)
        finally:
            db.close()
```

- [ ] **Step 5: 接進 create_event 路由**

`event_routes.py` 的 import 行改成（補 `watch_delivery`）：

```python
from event_service import handle_incoming_event, serialize_event, watch_delivery, DeviceNotFoundError
```

`create_event` 函式改成（`asyncio.create_task` 放路由層這個 async 函式裡，不放進同步的 `handle_incoming_event`）：

```python
@router.post("/events", status_code=201, dependencies=[Depends(require_api_key)])
async def create_event(body: EventCreateRequest, db: Session = Depends(get_db)):
    try:
        payload = handle_incoming_event(db, body.model_dump())
    except DeviceNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # 廣播後啟動背景任務盯送達。放這裡而非 handle_incoming_event 內：
    # 路由是 async、有 event loop；handle_incoming_event 是同步、被測試直接呼叫時沒 loop
    asyncio.create_task(watch_delivery(payload["event_id"]))
    return payload
```

- [ ] **Step 6: Run test to verify it passes**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/ -v`
Expected: PASS（全部測試；`test_events_post.py` 不受背景任務影響——interval=10 秒，測試在毫秒內結束前不會觸及正式 DB）

- [ ] **Step 7: 記錄多 worker 限制**

`docs/future-work.md` 加一條（放在 SSE / 擴展相關段落，或檔尾）：

```markdown
- **重推計時器與 SSE 連線池皆存記憶體，僅單一程序有效**：多 worker（uvicorn --workers N）上線時，事件與連線可能落在不同程序而對不起來，需一併改用 Redis Pub/Sub 共享。
```

- [ ] **Step 8: Commit**

```bash
git add event_service.py event_routes.py tests/conftest.py tests/test_delivery.py docs/future-work.md
git commit -m "feat: watch_delivery 重推背景任務接進 POST /events"
```

---

## Self-Review

- **Spec coverage**：§2 訊號來源→Task 3；§3 notified_at→Task 1；§4 ack 端點→Task 3；§5 重推計時器→Task 2/4/5；§6 已知限制→Task 5 Step 7；§7 序列化→Task 1。全數涵蓋。
- **型別一致**：`is_delivered(db, event_id)->bool`、`rebroadcast_event(db, event_id)->None`、`watch_delivery(event_id, *, session_factory, interval, max_attempts)` 各任務簽名一致。
- **無 placeholder**：所有步驟含實際程式碼與指令。

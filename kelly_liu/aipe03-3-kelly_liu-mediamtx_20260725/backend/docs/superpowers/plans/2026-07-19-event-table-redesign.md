# 事件表改版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `detect_events` 移除 `severity`/`yolo_threshold`/`staff_id`，新增 `verdict_by`/`resolved_by`（誰點的誰負責，員編由 JWT 自動記錄），並刪除 `GET /staff` 端點。

**Architecture:** 先加後拆（expand-then-contract）：Task 1 加新欄位（不刪舊的）→ Task 2/3 把 verdict/resolve 的寫入邏輯切到新欄位 → Task 4 拆掉 staff_id → Task 5 刪 GET /staff → Task 6 重建 RDS 表＋更新文件。每個 Task 結束時全部測試皆綠。

**Tech Stack:** FastAPI + SQLAlchemy 2.0（Mapped/mapped_column）+ pytest（in-memory SQLite）+ PostgreSQL（AWS RDS）

**Spec:** `backend/docs/superpowers/specs/2026-07-19-event-table-redesign-design.md`（實作以此為準）

## Global Constraints

- 測試指令（PowerShell 全新 session 不繼承 venv，用完整路徑）：
  `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest -v`
- **commit 一律由使用者執行**：每個 Task 結尾停下來提醒，不代打；commit 訊息**不加** Co-Authored-By 或模型署名
- 前置狀態：工作區已有未 commit 的 severity/yolo_threshold 刪除（models/router/service）與 spec 檔——**開工前先提醒使用者把這批 commit 掉**（建議訊息 `feat: 事件表移除 severity 與 yolo_threshold` + `docs: 事件表改版 spec`）
- RDS 的 `detect_events` 表與 `event_severity` ENUM 型別已於 2026-07-18 DROP，Task 6 之前**不可**對正式環境跑事件功能
- 員編來源固定為 `current_user["sub"]`（JWT payload，login 時由 `create_access_token(data={"sub": user.employee_id, ...})` 寫入）
- 測試種子（conftest.py）：帳號 `alice`（staff）/`boss`（admin）、裝置 device_id=1、照護員 staff 表 2 筆——**conftest 全程不動**

---

### Task 1: model 加 verdict_by / resolved_by（先加不拆）

**Files:**
- Modify: `backend/core/models.py`（DetectEvent，staff_id 那行下方）
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `DetectEvent.verdict_by: Optional[str]`、`DetectEvent.resolved_by: Optional[str]`（String(50)、nullable、FK→`user_account.employee_id`）。Task 2/3 的路由寫入、Task 2 的 serialize 輸出都用這兩個屬性名。
- 注意：`staff_id` 此時**還在**（Task 4 才拆），其他測試不受影響。

- [ ] **Step 1: 改 test_models.py 的第一條測試，加新欄位斷言（失敗的測試）**

把 `test_建立事件_預設狀態是pending` 的斷言區改成：

```python
    assert event.event_id  # UUID 字串自動產生
    assert event.status == "pending"   # 後端預設，不靠外部指定
    assert event.verdict is None       # 還沒人判定
    assert event.verdict_by is None    # 還沒人按判定（Task 1 新增）
    assert event.resolved_by is None   # 還沒人按結案（Task 1 新增）
    assert event.staff_id is None      # 舊欄位，Task 4 移除
```

- [ ] **Step 2: 跑測試確認紅**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest backend/tests/test_models.py -v`
Expected: FAIL，`AttributeError: 'DetectEvent' object has no attribute 'verdict_by'`

- [ ] **Step 3: models.py 加兩個欄位**

在 `DetectEvent` 的 `staff_id` 那行之後、`company_id` 之前插入：

```python
    # 誰點的誰負責：兩欄都存 user_account 的員編（JWT 的 sub），不是 staff 表的數字 id
    verdict_by: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("user_account.employee_id"), nullable=True
    )  # 判定者：按下 verdict 的人；真跌倒、誤報都記
    resolved_by: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("user_account.employee_id"), nullable=True
    )  # 結案者：按下 resolve 的人；誤報一鍵結案時與 verdict_by 同人
```

- [ ] **Step 4: 跑全部測試確認綠**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest -v`
Expected: 全部 PASS（staff_id 還在，既有測試不受影響）

- [ ] **Step 5: 提醒使用者 commit**

建議訊息：`feat: detect_events 加 verdict_by/resolved_by 欄位`

---

### Task 2: verdict 端點改「誰點的誰負責」＋ serialize 輸出新欄位

**Files:**
- Modify: `backend/events/router.py`（VerdictRequest + verdict_event）
- Modify: `backend/events/service.py`（serialize_event）
- Test: `backend/tests/test_verdict.py`

**Interfaces:**
- Consumes: Task 1 的 `event.verdict_by` / `event.resolved_by`
- Produces: `PATCH /events/{id}/verdict` 的 body 變成只有 `{"verdict": ...}`；serialize_event 輸出多 `"verdict_by"`、`"resolved_by"` 兩個 key（Task 3 的測試斷言依賴它們）

- [ ] **Step 1: 重寫 test_verdict.py（失敗的測試）**

整檔改成（8 條變 6 條：刪掉 422/400 兩條，其餘改斷言）：

```python
# 測 PATCH /events/{id}/verdict：值班人員判定真跌倒/誤報
# 2026-07-19 改版：誰點的誰負責——操作員由後端從 JWT 記錄，body 不再帶人
from backend.events.sse import pool


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
    assert data["status"] == "resolved"      # 誤報直接結案
    assert data["verdict"] == "false_alarm"
    assert data["verdict_by"] == "alice"     # auth_headers 是 alice 的 token
    assert data["resolved_by"] == "alice"    # 一鍵結案：判定者同時記為結案者


def test_判真跌倒_進入處理中並記錄判定者(client, auth_headers, make_event):
    event = make_event()

    res = client.patch(
        f"/events/{event.event_id}/verdict",
        json={"verdict": "true_alarm"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "in_progress"
    assert data["verdict"] == "true_alarm"
    assert data["verdict_by"] == "alice"
    assert data["resolved_by"] is None       # 還沒結案


def test_已判定過再判_409(client, auth_headers, make_event):
    # 造一筆已經判定過的事件（另一個值班人員搶先處理了）
    event = make_event(status="in_progress", verdict="true_alarm", verdict_by="boss")
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

- [ ] **Step 2: 跑測試確認紅**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest backend/tests/test_verdict.py -v`
Expected: FAIL——真跌倒那條收 422（舊規則還在要 staff_id）、誤報那條 `KeyError: 'verdict_by'`（serialize 還沒輸出）

- [ ] **Step 3: 改 router.py 的 VerdictRequest 與 verdict_event**

VerdictRequest 整個換成（不再收 staff_id）：

```python
# ── PATCH /events/{id}/verdict 收到的 JSON 格式 ──
# 不收任何「人」的欄位：誰點的誰負責，操作員由後端從 JWT 記錄
class VerdictRequest(BaseModel):
    verdict: Literal["true_alarm", "false_alarm"]
```

verdict_event 內的判定區塊（從 `if body.verdict == "true_alarm":` 到 `event.verdict = "false_alarm"`）換成：

```python
    operator = current_user["sub"]  # JWT 的 sub 就是員編：誰按的誰負責
    if body.verdict == "true_alarm":
        event.status = "in_progress"
        event.verdict = "true_alarm"
        event.verdict_by = operator
    else:
        # 誤報：判定即結案，同一個按鈕同時記判定者與結案者
        event.status = "resolved"
        event.verdict = "false_alarm"
        event.verdict_by = operator
        event.resolved_by = operator
```

（原本查 Staff 驗證的 422/400 區塊整段刪除；`Staff` import 先留著，`GET /staff` 還在用，Task 5 才拆）

- [ ] **Step 4: service.py 的 serialize_event 加輸出**

在 `"staff_id": event.staff_id,` 之後加：

```python
        "verdict_by": event.verdict_by,
        "resolved_by": event.resolved_by,
```

- [ ] **Step 5: 跑全部測試確認綠**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest -v`
Expected: 全部 PASS

- [ ] **Step 6: 提醒使用者 commit**

建議訊息：`feat: verdict 改誰點的誰負責，自動記 verdict_by/resolved_by`

---

### Task 3: resolve 端點記 resolved_by

**Files:**
- Modify: `backend/events/router.py`（resolve_event）
- Test: `backend/tests/test_resolve.py`

**Interfaces:**
- Consumes: Task 1 的 `event.resolved_by`、Task 2 的 serialize 輸出 `"resolved_by"`
- Produces: `PATCH /events/{id}/resolve` 執行後 `resolved_by=操作者員編`

- [ ] **Step 1: 更新 test_resolve.py（失敗的測試）**

`make_event(..., staff_id=1)` 三處（test_未登入_401、test_處理中的事件可以結案、test_結案成功會廣播event_updated）改成 `verdict_by="boss"`，並在 `test_處理中的事件可以結案` 加兩條斷言。改完的成功條長這樣：

```python
def test_處理中的事件可以結案(client, auth_headers, make_event):
    event = make_event(status="in_progress", verdict="true_alarm", verdict_by="boss")

    res = client.patch(f"/events/{event.event_id}/resolve", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "resolved"
    assert data["verdict"] == "true_alarm"  # 判定結果不變，只改進度
    assert data["verdict_by"] == "boss"     # 判定者不被結案動作覆蓋（換班情境）
    assert data["resolved_by"] == "alice"   # 結案者＝按結案的人（alice 的 token）
```

- [ ] **Step 2: 跑測試確認紅**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest backend/tests/test_resolve.py -v`
Expected: FAIL，`assert data["resolved_by"] == "alice"` 那條（目前是 None）

- [ ] **Step 3: resolve_event 加一行**

在 `event.status = "resolved"` 之後加：

```python
    event.resolved_by = current_user["sub"]  # 誰按結案誰負責
```

- [ ] **Step 4: 跑全部測試確認綠**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest -v`
Expected: 全部 PASS

- [ ] **Step 5: 提醒使用者 commit**

建議訊息：`feat: resolve 自動記 resolved_by`

---

### Task 4: 拆掉 staff_id（欄位、輸出、測試殘留）

**Files:**
- Modify: `backend/core/models.py`（刪 staff_id）
- Modify: `backend/events/service.py`（serialize 刪 staff_id）
- Test: `backend/tests/test_models.py`、`backend/tests/test_delivery.py`

**Interfaces:**
- Consumes: Task 2/3 完成後已無任何程式寫入 `event.staff_id`
- Produces: `DetectEvent` 不再有 `staff_id` 屬性；serialize 輸出不再有 `"staff_id"` key

（拆除方向沒有「先紅後綠」——先把測試裡的引用清掉，再拆本體，全程保持綠）

- [ ] **Step 1: 清掉測試裡的 staff_id 引用**

test_models.py：刪掉 `assert event.staff_id is None      # 舊欄位，Task 4 移除` 這行。
test_delivery.py：兩處 `make_event(status="in_progress", verdict="true_alarm", staff_id=1)`（test_is_delivered_status非pending即已送達、test_watch_delivery_已被處理_不重推）改成 `verdict_by="alice"`：

```python
    event = make_event(status="in_progress", verdict="true_alarm", verdict_by="alice")
```

- [ ] **Step 2: 跑全部測試確認綠（引用清乾淨的證據）**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest -v`
Expected: 全部 PASS

- [ ] **Step 3: models.py 刪 staff_id 欄位**

刪掉這行：

```python
    staff_id: Mapped[Optional[int]] = mapped_column(ForeignKey("staff.staff_id"), nullable=True)  # 判真跌倒時指派
```

- [ ] **Step 4: service.py 的 serialize_event 刪輸出**

刪掉這行：

```python
        "staff_id": event.staff_id,
```

- [ ] **Step 5: 跑全部測試確認綠**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest -v`
Expected: 全部 PASS

- [ ] **Step 6: 提醒使用者 commit**

建議訊息：`feat: detect_events 移除 staff_id`

---

### Task 5: 刪 GET /staff 端點

**Files:**
- Modify: `backend/events/router.py`（刪端點 + 刪 Staff import）
- Delete: `backend/tests/test_staff.py`

**Interfaces:**
- Consumes: Task 2 已把 verdict 裡的 Staff 查詢移除，此時 router 只剩 `GET /staff` 在用 `Staff`
- Produces: 路由表不再有 `GET /staff`；`staff` 資料表與種子保留（休眠，僅 conftest / init_db / test_models 還碰）

- [ ] **Step 1: 刪 test_staff.py**

```powershell
Remove-Item backend\tests\test_staff.py
```

- [ ] **Step 2: router.py 刪端點與 import**

刪掉整段 `GET /staff`（含上方註解框）：

```python
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

import 那行 `from backend.core.models import DetectEvent, Device, Staff` 改成：

```python
from backend.core.models import DetectEvent, Device
```

- [ ] **Step 3: 跑全部測試確認綠**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest -v`
Expected: 全部 PASS（test_staff.py 已不存在）

- [ ] **Step 4: 提醒使用者 commit**

建議訊息：`feat: 移除 GET /staff 端點`

---

### Task 6: RDS 重建、端到端煙霧測試、文件更新

**Files:**
- Modify: `CLAUDE.md`（路由表、資料庫段落）
- Modify: `backend/docs/mvp-acceptance-runbook.md`（選填欄位清單）

**Interfaces:**
- Consumes: Task 1–5 全部完成、全測試綠
- Produces: 正式 RDS 的 `detect_events` 為新 schema；文件與現況一致

- [ ] **Step 1: 重建正式 RDS 的 detect_events**

Run: `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m backend.init_db`
Expected: 建表訊息（既有表/帳號自動略過不報錯）。表已於 2026-07-18 DROP，此步會依新 model 重建。

- [ ] **Step 2: 端到端煙霧測試（手動）**

起服務：`uv run uvicorn backend.main:app --reload`，另開終端：

```powershell
# 1. 登入拿 token（admin / 123456）
$login = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/login -Body @{ username = "admin"; password = "123456" }
$h = @{ Authorization = "Bearer $($login.access_token)" }

# 2. 建一筆事件（故意帶 severity，驗證會被忽略而不是報錯）
$body = '{"device_id":1,"event_type":"fall","clip_path":"s3://clips/smoke.mp4","detected_at":"2026-07-19T10:00:00","severity":"high"}'
$ev = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/events -Headers @{ "X-API-Key" = "<.env 的 EVENT_API_KEY>" } -ContentType "application/json" -Body $body
$ev   # 確認：沒有 severity/yolo_threshold/staff_id，verdict_by/resolved_by 皆空

# 3. 判誤報 → 一鍵結案
Invoke-RestMethod -Method Patch -Uri "http://127.0.0.1:8000/events/$($ev.event_id)/verdict" -Headers $h -ContentType "application/json" -Body '{"verdict":"false_alarm"}'
# 確認：status=resolved、verdict_by=admin、resolved_by=admin
```

- [ ] **Step 3: 更新 CLAUDE.md**

路由表：刪 `GET /staff` 那列；verdict 那列說明改為
`判定：誤報→直接結案；真跌倒→處理中；操作員自動記入 verdict_by/resolved_by`。
「注意事項」外的資料庫段落：`status/verdict/severity 用原生 SQLAlchemy Enum` 改為 `status/verdict 用原生 SQLAlchemy Enum`。
檔案結構表：`events/router.py` 的「事件 6 個端點 + SSE」改「事件 5 個端點 + SSE」。

- [ ] **Step 4: 更新 mvp-acceptance-runbook.md**

選填欄位那行改為：`**選填**：snapshot_path、yolo_score、vlm_summary；多送的欄位會被忽略。`

- [ ] **Step 5: 提醒使用者 commit ＋ 轉達前端**

建議訊息：`docs: 事件表改版後更新 CLAUDE.md 與驗收文件`
轉達前端三件事（見 spec「前端知會事項」）：severity/yolo_threshold 移除、staff_id 改 verdict_by/resolved_by（員編字串）、誤報只打 verdict 一支（現行多打 resolve 會 409）。

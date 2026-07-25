# 事件表改版：刪減欄位＋操作員記錄（2026-07-19）

## 目標

1. `detect_events` 移除 `severity`、`yolo_threshold`（不再需要）。
2. 廢除「指派照護員」概念，改為**誰點的誰負責**：判定與結案的操作員由後端從 JWT 自動記錄，前端不再送任何「人」的欄位。
3. 移除 `GET /staff` 端點（前端未使用；未來若需指派功能另開新路由）。

## 資料表變更（detect_events）

| 動作 | 欄位 | 型別／約束 | 說明 |
|------|------|-----------|------|
| 移除 | `severity` | — | 連同 PostgreSQL ENUM 型別 `event_severity` 一併移除 |
| 移除 | `yolo_threshold` | — | |
| 移除 | `staff_id` | — | 含指向 `staff` 表的 FK；`staff` 表本身保留（休眠，無程式引用） |
| 新增 | `verdict_by` | String(50)、nullable、FK→`user_account.employee_id` | 判定者：按下 verdict（true_alarm 或 false_alarm）的登入者員編 |
| 新增 | `resolved_by` | String(50)、nullable、FK→`user_account.employee_id` | 結案者：按下 resolve 的登入者員編；誤報一鍵結案時與 `verdict_by` 同值 |

- 兩個新欄位在事件建立（pending）時皆為 NULL。
- String(50) 對齊 `user_account.employee_id`。
- 員編來源：`current_user["sub"]`（JWT payload，login 時寫入）。

## 端點行為變更

### PATCH /events/{event_id}/verdict

- Request body 改為 `{"verdict": "true_alarm" | "false_alarm"}`，**不再收 staff_id**。
- `true_alarm`：`status=in_progress`、`verdict_by=操作者員編`。
- `false_alarm`：`status=resolved`、`verdict_by=操作者員編`、`resolved_by=操作者員編`（一鍵結案，兩欄同時填）。
- 移除規則：「true_alarm 未帶 staff_id 回 422」「staff_id 查無回 400」（JWT 可解開即保證操作者存在）。
- 不變：401（未登入）、404（事件不存在）、409（已判定過）、判定後廣播 `event_updated`。

### PATCH /events/{event_id}/resolve

- 新增：`resolved_by=操作者員編`。
- 其餘不變（409 守門：僅 in_progress 可結案；廣播 `event_updated`）。

### GET /staff

- 整支端點刪除。

### serialize_event（SSE 廣播與 GET /events 共用）

- 移除輸出欄位：`staff_id`、`severity`、`yolo_threshold`。
- 新增輸出欄位：`verdict_by`、`resolved_by`。

### POST /events（判斷層入口）

- `EventCreateRequest` 移除 `severity`、`yolo_threshold`（已完成）。producer 多送的欄位由 Pydantic 忽略，AI 端無需同步改版。

## 不變的部分

狀態機（pending→in_progress→resolved）、SSE 連線池與廣播時機、ack／重推（at-least-once）、Kafka consumer、`staff` 表與其種子資料。

## 測試變更

| 檔案 | 變更 |
|------|------|
| `test_verdict.py` | 刪「422 未帶人」「400 查無此人」兩條；斷言改 `verdict_by`；誤報條加斷言 `resolved_by` 同值 |
| `test_resolve.py` | 加斷言 `resolved_by`；`make_event(staff_id=1)` 改 `verdict_by="boss"`（boss 判定、alice 結案，驗證判定者不被結案動作覆蓋） |
| `test_delivery.py` | `make_event(staff_id=1)` 改 `verdict_by="alice"` |
| `test_models.py` | `staff_id is None` 改 `verdict_by is None` ＋ `resolved_by is None` |
| `test_staff.py` | 整檔刪除 |
| `conftest.py` | 不動（make_event 以 kwargs 透傳；Staff 種子保留） |

## 部署步驟

1. RDS 的 `detect_events` 與 `event_severity` 型別已 DROP（2026-07-18），程式改完後執行 `python -m backend.init_db` 依新 schema 重建。
2. 更新 CLAUDE.md：路由表移除 `GET /staff`、verdict 說明改為「不帶人，後端自動記錄操作員」、資料庫段落更新欄位清單。

## 前端知會事項

1. 回應欄位移除：`severity`、`yolo_threshold`。
2. `staff_id` 改為 `verdict_by`／`resolved_by`（值為員編字串，非數字 id）。
3. 誤報流程只需打 `PATCH /events/{id}/verdict`（`false_alarm` 會直接結案）；現行前端 verdict 後再打 resolve 會收到 409（既有行為，非本次造成）。

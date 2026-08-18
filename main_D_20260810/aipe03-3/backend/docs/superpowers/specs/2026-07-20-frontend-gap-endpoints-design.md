# 前端串接補齊：devices / reports / users 端點設計

對照前端整合文件（AIPE03-3/aipe03-3 `frontend/BACKEND_INTEGRATION.md`，2026-07-18 版）
盤點出的三組缺口，本輪補齊：

- **M1**：鏡頭清單 `GET /devices` + 改名 `PATCH /devices/{device_id}`
- **M2**：通報單 `POST /events/{event_id}/reports` + `GET /events/{event_id}/reports`（含新表）
- **M3**：使用者管理 `GET /users` + `PATCH /users/{user_id}`

欄位命名、enum 值一律以後端既有字彙為準，前端在其 `src/api/` 層做對照
（前端架構原則：所有前後端接縫集中在 api 層消化）。

---

## M1：devices（新資料夾 `backend/devices/`）

### GET /devices（需登入）

查全部裝置，JOIN `locations` 夾帶位置資訊，回陣列：

```json
[
  {
    "device_id": 1,
    "device_name": "鏡頭1",
    "location": "交誼廳",
    "floor": "2F",
    "stream_url": null,
    "status": "active"
  }
]
```

- `location` = `locations.location_name`；裝置沒設位置（`location_id` 為 NULL）時 `location`、`floor` 回 null
- `status` 回後端既有 enum：`active` / `inactive` / `fault`，**不**改成前端的
  `online` / `offline` / `disabled`（改名需對 RDS 跑 `ALTER TYPE`，前端在 api 層對照只要三行）。
  語意對應：`active`→`online`、`fault`→`offline`（故障＝暫時離線）、`inactive`→`disabled`（人為停用）
- 前端 `Camera.stream_source`（渲染方式描述，`{type, url}`）是前端由 `stream_url` 加工的
  衍生欄位，且其 mock 目前一律 null、尚未實作渲染；後端只提供 `stream_url`

### PATCH `/devices/{device_id}`（需 admin）

- body：`{ "device_name": str }`（min_length=1）
- 裝置不存在回 404；成功回更新後單筆（與 GET 同格式）
- **只收 `device_name`**。`location_name` / `floor` 是 `locations` 表的欄位，從裝置端點改會
  波及同區域所有裝置與歷史事件的顯示位置（`detect_events.location_id` 凍結設計的保護對象），
  區域管理是獨立功能，本輪不做

---

## M2：通報單（新資料夾 `backend/reports/` + 新表）

### 為什麼整包存 JSON（方案 A）

通報單是前端定義的政府制式表單（約 30 欄，中文選項），定義權在前端；
後端只負責保管與吐回，不查詢個別欄位。整包存 JSON 讓表單改版時後端零修改。
唯一需要獨立查詢的 `report_type` 抽出成欄。

### 新表 `detect_event_reports`

| 欄位            | 型別                                      | 約束                                       | 說明                                   |
| --------------- | ----------------------------------------- | ------------------------------------------ | -------------------------------------- |
| `report_id`   | Integer                                   | PK, autoincrement                          | 不對外系統曝光，不需 UUID              |
| `event_id`    | String(36)                                | FK→`detect_events.event_id`, not null   | 所屬事件                               |
| `report_type` | Enum(`initial`,`follow_up`,`final`) | not null,`create_constraint=True`        | 初報/續報/結報，照 status/verdict 慣例 |
| `form`        | JSON                                      | not null                                   | 表單整包，程式端讀寫是 dict            |
| `created_by`  | String(50)                                | FK→`user_account.employee_id`, not null | 從 JWT`sub` 記，前端不帶             |
| `created_at`  | DateTime                                  | not null                                   | 後端寫入當下時間                       |

- 無 unique 約束：同事件可存多筆同類型（前端設計即為每次儲存獨立累積一筆）
- 不加 `company_id`：公司資訊經 `event_id` JOIN `detect_events` 可得；多租戶過濾 MVP 未做（既定方向）

### POST `/events/{event_id}/reports`（需登入）

- body：`{ "report_type": "initial" | "follow_up" | "final", "form": {…} }`
- 事件不存在回 404；`report_type` 非法值由 Pydantic Literal 擋 422
- `created_by` 由後端從 JWT 填入（同 verdict_by/resolved_by 的「誰點的誰負責」模式）
- 成功回 201 + 該筆完整資料

### GET `/events/{event_id}/reports`（需登入）

- 事件不存在回 404；無通報單回空陣列
- **排序：舊→新**（`created_at` 升冪，同時間以 `report_id` 升冪決勝）。
  前端 `getLatestReport` 取陣列最後一筆當最新，順序契約必須一致
- 每筆：

```json
{
  "report_id": 1,
  "event_id": "uuid…",
  "report_type": "initial",
  "form": { "…": "…" },
  "created_by": "staff01",
  "created_at": "2026-07-20T10:00:00"
}
```

---

## M3：使用者管理（加在既有 `backend/users/router.py`）

### GET /users（需 admin）

- 只回 `is_active=True` 的帳號（停用帳號不出現在管理名單）
- 白名單式只回四欄，永不回傳 `password`：

```json
[{ "id": 1, "employee_id": "staff01", "full_name": "王小明", "role": "staff" }]
```

### PATCH `/users/{user_id}`（需 admin）

- body：`{ "full_name": str }`（min_length=1）
- 使用者不存在回 404；成功回 `{ id, employee_id, full_name, role }`
- **只收 `full_name`**：
  - 不收 `role`：防權限竄改，本輪也無此需求
  - 不收密碼：重設密碼已有專屬端點 `PATCH /users/{user_id}/password`
    （含 `must_change_password=True` 的特殊行為），一件事一個入口。
    前端「編輯使用者」頁一鍵儲存名稱＋密碼 → 由前端 api 層拆成兩支呼叫

---

## 權限總表

| 端點                                | 權限     |
| ----------------------------------- | -------- |
| `GET /devices`                    | 登入即可 |
| `PATCH /devices/{device_id}`      | admin    |
| `POST /events/{event_id}/reports` | 登入即可 |
| `GET /events/{event_id}/reports`  | 登入即可 |
| `GET /users`                      | admin    |
| `PATCH /users/{user_id}`          | admin    |

沿用既有依賴：`get_current_user` / `require_admin`。

---

## 給前端的對齊清單（實作後隨 API 文件一併通知）

1. `devices.status`：後端回 `active`/`inactive`/`fault`，前端 api 層對照成
   `online`/`offline`/`disabled`（對應關係見 M1）
2. 使用者欄位：後端回 `employee_id`/`full_name`，前端 `ManagedUser` 的
   `employee_code`/`name` 在 api 層對照；`id` 為數字，前端需 `String(id)`
3. 密碼最短長度：後端為 6 碼，前端 `UserDetail.tsx` 的 `PASSWORD_MIN_LENGTH = 4` 需改為 6
4. `report_type` 收英文值 `initial`/`follow_up`/`final`，前端既有
   `REPORT_TYPE_TO_STAGE` 對照可直接用；回應的 `created_at` 對應前端 `savedAt`
5. **（待確認，非本輪範圍）** 誤報流程 409：前端目前誤報＝先 `PATCH /verdict`（false_alarm）
   再 `PATCH /resolve`；後端 false_alarm 即直接結案，第二支 resolve 會回 409。
   解法兩案待與前端定案：A）前端誤報後不再打 resolve；B）後端 resolve 對已結案事件
   改回 200（冪等）。定案前兩邊都先不動
6. 事件的操作員欄位：`staff_id` 已移除，改為 `verdict_by`/`resolved_by`（員編字串）

---

## 錯誤處理慣例（沿用既有）

| 情況                               | 回應            |
| ---------------------------------- | --------------- |
| 未帶 token / token 無效            | 401             |
| 非 admin 打 admin 端點             | 403             |
| 路徑資源不存在（裝置/事件/使用者） | 404             |
| body 欄位缺漏或非法值              | 422（Pydantic） |

---

## 測試策略

照專案慣例：`backend/tests/`，in-memory SQLite，TDD。各端點至少涵蓋：

- 正常流程（含回應欄位形狀）
- 權限：未登入 401、非 admin 403（admin 端點）
- 404：資源不存在
- M2 另加：多筆累積不覆蓋、排序舊→新、`created_by` 取自 JWT、`form` 原樣存取
- M1 另加：無位置裝置的 `location`/`floor` 回 null
- M3 另加：停用帳號不出現在 `GET /users`、回應不含 `password`

## 本輪不做

- `hazard_object` / `severity` / `yolo_threshold` 欄位（前端可吃預設，AI 端目前不產 hazard 事件）
- 區域（locations）管理端點
- `company_id` 多租戶過濾（既定延後，見 future-work）
- email OTP 登入端點（前端將切 `AUTH_MODE=employee_password` 接既有 `/login`）
- KPI 端點（M4，另輪）

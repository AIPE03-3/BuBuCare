# 跌倒事件通報 + SSE 推播 + 人工確認 — 設計規格

> 日期：2026-07-02
> 狀態：已與使用者逐段確認完成
> 前置討論的決策結論已併入本文件第 9 節（原 `docs/event-sse-discussion-handoff.md` 已刪除）

---

## 1. 目標與範圍

在 fulilian-backend（通報層 FastAPI）新增「跌倒事件」完整流程：

1. 判斷層偵測到跌倒 → `POST /events` 進後端 → 存 PostgreSQL
2. 後端用 SSE 即時推播給前端中控站（支援多客戶端）
3. 值班人員確認：真實跌倒（同時指派照護員）或誤報
4. 真實跌倒 → 照護員處理 → 標記結案

**不在範圍內**：Kafka 實接（只預留介面）、Web Push、模型回訓（ML pipeline 負責）、多租戶過濾邏輯（只預留欄位）。

---

## 2. 架構與資料流

```
判斷層（未來是 Kafka consumer）
    │ POST /events + X-API-Key
    ▼
handle_incoming_event()   ← 共用處理函式，Kafka 接上時也呼叫它
    │ 1. 存 PostgreSQL（失敗回錯，不廣播）
    │ 2. 成功 → SSE 廣播 event_created
    ▼
前端中控站（多台同時開）
    │ PATCH /events/{id}/verdict → 存 DB → 廣播 event_updated
    │ PATCH /events/{id}/resolve → 存 DB → 廣播 event_updated
```

**設計原則**：

- 事件「入口」（POST / 未來 Kafka consumer）與「處理」（存 DB + 廣播）拆開。Kafka 接上時只是新增入口，`handle_incoming_event()` 零改動，`POST /events` 保留當測試/備援入口
  > **2026-07-11 更新**：Kafka 已實接，實際 topic 是 `processed-reports`（非當初預想的 `vlm.verdicts`），且 consumer 是獨立行程「轉打 POST /events」而非直呼函式。實際接法見 `docs/superpowers/specs/2026-07-09-kafka-consumer-design.md`。
- 先存 DB 成功才廣播，資料庫是唯一真相

---

## 3. 狀態機（拆兩欄）

| 欄位 | 值 | 意義 |
|--|--|--|
| `status` | `pending` → `in_progress` → `resolved` | 事件進度 |
| `verdict` | `null` / `true_alarm` / `false_alarm` | 人工判定結果，判定時才填 |

合法轉換（後端強制檢查，違反回 409）：

| 目前狀態 | 動作 | 結果 |
|--|--|--|
| `pending` | 判定誤報 | `status=resolved, verdict=false_alarm`（直接結案） |
| `pending` | 判定真跌倒（必帶 staff_id） | `status=in_progress, verdict=true_alarm` |
| `in_progress` | resolve | `status=resolved` |

未來擴充成完整生命週期（suppressed / cooldown / escalated 等）時，只在 `status` 加值，不改語意。

---

## 4. 資料庫

### 這次新建 5 張表

> Not null 原則：欄位一律 not null，可空的例外有——`devices.location_id` 和 `devices.stream_url`（裝置剛建檔時可能還沒定位置、還沒接串流，強制填只會逼人塞假資料）、`locations.floor`（中庭、戶外等沒有明確樓層的地點可留白）、`detect_events.location_id`（來源 `device.location_id` 本身可空，抄過來也可能是空）。

**companies**：`company_id`(INT PK autoincrement)、`company_name`(VARCHAR not null)。種一筆預設公司（id=1），本輪所有資料掛它底下。

**locations**：`location_id`(INT PK autoincrement)、`location_name`(VARCHAR(50) not null，如「交誼廳」「走廊」)、`floor`(VARCHAR(10) **nullable**，純字串樓層標籤如「B1」「1F」「夾層」「RF」)、`company_id`(INT FK→companies, not null)。區域獨立成表讓地點名稱統一。

> **2026-07-07 設計更新**：原設計「區域不連 events、位置靠兩層 FK 現查」已改為**事件建立時凍結位置**（見下方 detect_events.location_id）。現在 events 透過自身凍住的 `location_id` 連到 locations。

**devices**：`device_id`(INT PK autoincrement)、`device_name`(VARCHAR not null)、`location_id`(INT FK→locations, **nullable**)、`status`(ENUM: active/inactive/fault, not null, default active)、`stream_url`(VARCHAR **nullable**)、`company_id`(INT FK→companies, not null)。

> **歷史正確性（2026-07-07 更新）**：位置改用**快照**保護——事件建立時把 `device.location_id` 凍進 `detect_events.location_id`，之後裝置搬到別的區域，舊事件顯示的仍是發生當下的位置。`device_name` 仍是顯示時經裝置現查（未快照），因此**裝置改名/改用途**時仍建議沿用原則：不改舊列，把舊列 `status` 設 `inactive`、另建一列新裝置，讓舊事件的裝置名稱維持歷史正確。

**staff**：`staff_id`(INT PK autoincrement)、`staff_name`(VARCHAR not null)、`company_id`(INT FK→companies, not null)。

**detect_events**：

| 欄位 | 型別 | 說明 |
|--|--|--|
| `event_id` | UUID PK | |
| `device_id` | INT FK→devices, not null | |
| `location_id` | INT FK→locations, nullable | 事件發生當下所在區域，寫入時從裝置 `location_id` 凍一份，之後不改（歷史正確）|
| `event_type` | VARCHAR(50) | 如 fall |
| `status` | ENUM: pending/in_progress/resolved, not null, default pending | 進度 |
| `verdict` | ENUM: true_alarm/false_alarm, nullable | 判定結果 |
| `clip_path` | VARCHAR(255) not null | 事件影像片段 |
| `snapshot_path` | VARCHAR(255) | 截圖 |
| `detected_at` | TIMESTAMP not null | |
| `staff_id` | INT FK→staff, nullable | 判真跌倒時指派 |
| `company_id` | INT FK→companies | |
| `yolo_score` | FLOAT | 該事件 YOLO 打的分數（如 0.87） |
| `yolo_threshold` | FLOAT | **當時**的門檻值（如 0.75）。門檻日後會調整，回訓分析需知道這筆當初用什麼門檻判進來。注意：修正草稿的 threshlod 拼字 |
| `vlm_summary` | TEXT | VLM 情境描述 |
| `severity` | ENUM: low/medium/high | |

### 既有表調整

**user_account**：新增 `company_id`(INT FK→companies, not null, **default 1**)。加欄位時舊帳號自動回填 1（預設公司），新註冊帳號也自動拿 1。程式碼唯一改動是 `models.py` 的 User 類多一行欄位定義；登入、註冊、驗證的邏輯零改動。

**locations**（2026-07-07）：新增 `floor`(VARCHAR(10), nullable)。
**detect_events**（2026-07-07）：新增 `location_id`(INT FK→locations, nullable)。

### 多租戶策略

Schema 欄位齊備、邏輯先支援單一機構：本輪 API 不做公司過濾（所有資料都掛預設公司 id=1），未來要真正多租戶時只需在查詢加 `WHERE company_id = ...`，不用搬資料。

---

## 5. API 端點（6 個）

| 端點 | 驗證 | 成功回應 | 錯誤 |
|--|--|--|--|
| `POST /events` | X-API-Key header | 201 + 事件 JSON | 401 key 錯/沒帶；400 device_id 不存在；422 格式錯 |
| `GET /stream?token=` | JWT（query 參數） | SSE 長連線 | 401 token 無效 |
| `GET /events` | JWT | 200 + 事件陣列（新→舊） | 401 |
| `GET /staff` | JWT | 200 + 照護員陣列 | 401 |
| `PATCH /events/{id}/verdict` | JWT | 200 + 更新後事件 | 404；409 已判定過；422 判真跌倒沒帶 staff_id；400 staff_id 不存在 |
| `PATCH /events/{id}/resolve` | JWT | 200 + 更新後事件 | 404；409 狀態非 in_progress |

### 驗證方式

- **機器（POST /events）**：`.env` 存 `EVENT_API_KEY`，判斷層在 header 帶 `X-API-Key`，比對一致才收
- **人（其餘端點）**：現有 JWT，staff 與 admin 角色皆可操作
- **SSE（GET /stream）**：瀏覽器建立 SSE 用的內建工具 `EventSource` 先天不允許自訂 header，所以同一張 JWT token 改放在網址參數 `?token=xxx`；後端從網址參數取出後，用與其他端點**同一個驗證函式**檢查（同一張門票，只是改插的位置）

### 請求格式

`POST /events` body：`device_id`、`event_type`、`clip_path`、`detected_at`（必填）；`snapshot_path`、`yolo_score`、`yolo_threshold`、`vlm_summary`、`severity`（選填）。status 一律由後端設為 `pending`，不接受外部指定。

`PATCH /events/{id}/verdict` body：`verdict`（true_alarm/false_alarm 必填）；`staff_id`（verdict=true_alarm 時必填）。

`PATCH /events/{id}/resolve`：無 body。

---

## 6. SSE 設計

### 訊息格式

兩種訊息類型，`data` 都是完整事件 JSON（後端把 `device_name`（裝置現查）、`location`（事件凍結的位置）一起送，前端零額外請求）：

```
event: event_created
data: {"event_id":"...","device_id":3,"device_name":"交誼廳-01","location":"交誼廳",
       "event_type":"fall","status":"pending","verdict":null,"severity":"high",
       "detected_at":"...","snapshot_path":"...","vlm_summary":"...",
       "staff_id":null, ...}

event: event_updated
data: {...同結構，狀態變更後的完整事件...}
```

- `event_created`：新事件入庫後廣播
- `event_updated`：verdict / resolve 成功後廣播（多台中控站畫面保持同步）
- `GET /events` 回傳的每筆事件使用**同一個 JSON 結構**（同一個序列化函式，同樣含 device_name / location），前端只需寫一套顯示邏輯
- **心跳**：每 15 秒送註解行 `: ping`，防止中間網路設備掐斷長連線

### 連線池（方案 A：全域記憶體）

- 每條 SSE 連線配一個 asyncio queue（信箱），連線池是「目前所有 queue」的 list
- 廣播 = 走訪 list，往每個 queue 投一份訊息副本；投遞端與收件端透過 queue 交接，互不等待
- 連線斷開（含 F5 重整）→ 該 queue 從 list 移除，不影響其他連線
- 單機夠用；未來水平擴展時換 Redis Pub/Sub

---

## 7. 錯誤處理三條底線

1. **存 DB 失敗 → 500，不廣播**（先存後播）
2. **廣播時某條連線掛了 → 踢出連線池，不影響其他連線**
3. **不合法狀態轉換一律 409**，轉換規則只寫在後端一處

---

## 8. 測試設計

沿用 `tests/conftest.py` 模式（in-memory SQLite，與正式 DB 隔離）。原則：**第 5 節表格承諾的每種行為，各寫一題**。

| 測試檔 | 涵蓋 |
|--|--|
| `test_events_post.py` | API key 對/錯/沒帶；正常建立；device_id 不存在 |
| `test_events_list.py` | 未登入 401；排序（新→舊）；能查到剛建立的事件 |
| `test_verdict.py` | 判誤報→直接 resolved；判真跌倒必帶 staff_id；重複判定 409；404 |
| `test_resolve.py` | 正常結案；未判定就 resolve→409；已結案再 resolve→409 |
| `test_staff.py` | 未登入 401；名單正確 |
| `test_sse.py` | 廣播函式單元測試：全部 queue 收到訊息；斷線連線被移除且不影響其他 |

SSE 策略：長連線本身不測「等待」，直接對連線池 + 廣播函式做單元測試（純邏輯）；`/stream` 端點只測 token 驗證擋不擋。

---

## 9. 既有決策沿用（來自前置討論）

- 組員確定引入 Kafka，本輪用 POST 模擬入口（後於 2026-07-11 實接，topic 定為 `processed-reports`，見 kafka-consumer spec）
- 只做 SSE，Web Push 未來「加上」而非「換掉」——護理站電腦本來就一直開著，SSE 管畫面即時更新，Web Push 管網頁沒開時的系統通知，兩者不衝突
- 模型回訓**目前**不是後端的工作，目前後端負責把誤報資料完整存好（含事件 ID、時間、影像路徑），供 ML pipeline 撈取
- `users` 草稿表不採用：沿用現有 `user_account`（僅加 nullable `company_id`）
- `users` = 有登入帳號者；`staff` = 被指派到現場的照護員，兩張表分開

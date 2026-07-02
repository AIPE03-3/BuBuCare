# 事件通報 + SSE 功能討論交接文件

> ✅ **設計討論已全部完成**（2026-07-02），本文件僅保留作討論過程紀錄。最新狀態：
>
> - **正式 spec**：`docs/superpowers/specs/2026-07-02-event-sse-design.md`（含後來的修訂：status/verdict 拆兩欄、locations 獨立表、裝置不改名原則）
> - **實作計畫**：`docs/superpowers/plans/2026-07-02-event-sse-implementation.md`（10 個任務，TDD）
> - **使用者已選定：逐步執行**（inline，每步先說明、同意才動手）
> - **開新對話請說**：「用 superpowers:executing-plans 逐步執行 docs/superpowers/plans/2026-07-02-event-sse-implementation.md，從 Task 1 開始」
>
> 以下為原始討論紀錄（部分決策已被 spec 修訂取代，以 spec 為準）。

---

## 一、要做的功能（範圍）

在 fulilian-backend（通報層 FastAPI）新增「跌倒事件」的完整流程：

1. 判斷層偵測到跌倒 → 事件進後端 → 存 PostgreSQL
2. 後端用 **SSE** 即時推播給前端中控站
3. 前端值班人員確認：真實跌倒 or 誤報
4. 真實跌倒 → 指派照護員處理 → 追蹤到「已處理」

---

## 二、已經確認的技術決策（附理由）

| 決策 | 結論 | 理由 |
|--|--|--|
| 事件怎麼進後端 | **組員確定會引入 Kafka**。這次採「**先設計好介面、用 POST /events 模擬**」的做法（選項 2） | 把「收到事件」的處理邏輯抽成一個共用函式（例如 `handle_incoming_event()`），POST 端點和未來的 Kafka consumer 都呼叫它。等組員的 Kafka 環境（topic: `vlm.verdicts`）好了再接上，**核心邏輯完全不用改**，只是多一個事件入口 |
| 即時推播技術 | **先只做 SSE** | 護理站電腦本來就一直開著。Web Push（像 YouTube 那種系統推播）較複雜，之後可「加上」而非「換掉」——SSE 管畫面即時更新，Web Push 管網頁沒開時的系統通知，兩者不衝突 |
| SSE 廣播方式 | **方案 A：全域連線池**（記憶體 list 維護所有連線，事件進來廣播給每一條） | 單機夠用、程式乾淨。未來擴展可換 Redis Pub/Sub。不用方案 B（Redis，太複雜）或方案 C（輪詢 DB，浪費資源） |
| 多客戶端支援 | **做多客戶端**（連線池） | 不只為了多人同時用，也為了健壯性：重新整理頁面時會短暫出現 0 條或 2 條連線，連線池能優雅處理 |
| 存 DB 和廣播順序 | **先存 DB，成功後才廣播** | 保證資料不遺失；若存 DB 失敗直接回錯，什麼都沒發生 |
| 模型回訓 | **不是後端的工作** | 後端只負責把誤報資料存好（含事件 ID、時間、S3 路徑），ML pipeline 另外去撈 Hard Negative Pool 重新訓練 |
| 多租戶（companies） | **要做**（schema 有 company_id） | schema 草稿設計成支援多間安養院 |

### ⭐ 關於 Kafka 的架構重點（最重要，別忘）

```
現在（這次做）：
  判斷層 ──POST /events──▶ [handle_incoming_event()] ──存DB──▶ SSE 廣播

未來（組員 Kafka 好了之後，只加不改）：
  判斷層 ──▶ [Kafka topic: vlm.verdicts] ──▶ FastAPI 背景 consumer ──┐
                                                                      ├─▶ [handle_incoming_event()] ──存DB──▶ SSE 廣播
  （POST /events 保留，可當測試/備援入口）───────────────────────────┘
```

**設計原則：事件「入口」（POST / Kafka consumer）和事件「處理」（存 DB + 廣播）要拆開。** 這樣 Kafka 接上時只是新增一個入口，處理邏輯零改動。

---

## 三、資料庫 Schema（依 `fulilian_schema.md.md` 草稿）

草稿已存在 `fulilian_schema.md.md`，包含 5 張表：
`devices`、`users`、`detect_events`、`staff`、`companies`

### 關鍵：`detect_events` 狀態機（草稿還沒補上 resolved，需補）

```
unverified ──→ true_alarm ──→ resolved
           ↘
             false_alarm
```

`status` ENUM 需要：`unverified`、`true_alarm`、`false_alarm`、`resolved`（最後這個草稿還沒寫，要加）

### 關鍵：users vs staff 的區別（已跟使用者確認）

- `users` = 有登入帳號、可操作中控站的人（值班人員、管理員）
- `staff` = 照護員，事件發生時被指派去現場處理，記在 `detect_events.staff_id`
- 兩者是同一群護理師，但分成兩張表

### 流程對應

```
判斷層送事件（unverified）
    ↓
users（值班人員）在中控站確認 → true_alarm or false_alarm
    ↓（true_alarm 時）
指派 staff（照護員）去現場，記錄 staff_id
    ↓
照護員處理完 → 標記 resolved
```

> ⚠️ 注意：目前程式碼裡的實際資料表叫 `user_account`（欄位 id/name/password/email/role/last_login_time），
> 和草稿的 `users` 表（user_id/username/password_hash/role/email/created_at/company_id）欄位名不一致。
> 開始實作前要先決定：沿用現有 `user_account` 還是遷移到草稿的 `users` 結構。

---

## 四、API 端點設計（討論到這裡，尚未定案）

目前提議 5 個端點，**等使用者確認是否足夠**：

| 方法 | 路徑 | 誰呼叫 | 說明 |
|--|--|--|--|
| `POST` | `/events` | 判斷層（未來 Kafka consumer 內部也走同一處理函式） | 新增跌倒事件（status = unverified） |
| `GET` | `/stream` | 前端瀏覽器 | 建立 SSE 長連線 |
| `GET` | `/events` | 前端瀏覽器 | 取得事件列表（含歷史） |
| `PATCH` | `/events/{id}/verdict` | 值班人員 | 回報 true_alarm / false_alarm，同時填 staff_id |
| `PATCH` | `/events/{id}/resolve` | 值班人員 | 標記 resolved |

**下一步：** 使用者確認端點後，繼續設計「SSE 訊息格式、權限、錯誤處理、測試」，再寫成正式 spec 到 `docs/superpowers/specs/`。

---

## 五、既有專案現況（背景）

- 帳號系統完成：register / login / me / delete，JWT + bcrypt，16 個測試全過
- DB：PostgreSQL（AWS RDS，ap-northeast-1），實際表名 `user_account`
- 測試：in-memory SQLite（`tests/conftest.py`），與正式 DB 隔離
- 啟動：`python -m uvicorn main:app --reload`（`uv run` 有 trampoline bug）
- 測試指令：`& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/ -v`

## 六、合作規則（重要）

- 使用者是**邊學邊做**，每一步動手前先用白話說明，等他看懂並同意才執行
- 不要自己連續執行多步
- 看不懂時換更具體的方式解釋，不要跳過

---

## 七、還沒討論到的（開新對話要繼續的）

- [ ] API 端點是否足夠（正在問）
- [ ] SSE 推送的訊息格式（要推整包事件還是只推 ID）
- [ ] 各端點的權限（誰能 POST /events？要不要驗證判斷層身分）
- [ ] 錯誤處理
- [ ] 測試設計（沿用 conftest.py 模式）
- [ ] users/user_account 表要不要重構
- [ ] 是否這次就做多租戶（companies），還是先寫死一間
- [ ] Kafka 介面怎麼抽（`handle_incoming_event()` 的參數與位置）
- [ ] 寫正式 spec → 實作計畫

# 未來強化清單

> 這裡記「現階段刻意不做、但上正式環境前要回頭做」的事項。
> 每項都寫清楚：為什麼現在不做、什麼時候該做。

## 安全強化

### 1. Refresh token + 短效 access token（上正式環境前必做）

- **現況**：單一 JWT，有效期 **8 小時**（`backend/core/config.py` 的 `ACCESS_TOKEN_EXPIRE_HOURS`）。
  2026-07-29 從 1 天縮短，理由是 JWT 無法撤銷——按登出只是前端丟掉 token，後端仍認得它，
  所以有效期是外流後唯一的止血點。8 小時＝約一個班次，值班中不會被登出。
- **問題**：仍有 8 小時的冒用窗口，且 `/stream` 的 token 放在網址上會進伺服器日誌。
  token 存在 localStorage，任何一段 JavaScript（含被下毒的 npm 套件）都讀得到。
- **做法**：改成兩張票——短效 access token（15~30 分鐘）+ 長效 refresh token（7~30 天，
  HttpOnly cookie 存放，JavaScript 讀不到），前端在 access token 快過期時自動換新的，使用者無感。
  兩張票才能同時要到「進門的票很短命」與「不用一直重新登入」。
- **為什麼現在不做**：要動登入流程骨幹（新端點、cookie、前端攔截、撤銷管理），
  出錯的症狀是「平常都好、某個時間點突然全體被登出」，很難在幾天內測出來，demo 前風險報酬比差。
  縮短有效期是同方向的簡化版，之後做 refresh 時只是把數字再改小，不會白做。

### 2. Nginx 日誌遮蔽 /stream 的 query 參數（架 nginx 時順手做）

- **現況**：`/stream?token=...` 的完整網址會被寫進存取日誌。目前只有 uvicorn 一份。
- **注意**：未來若在前面架 nginx（自架的算自家日誌，風險等級不變），nginx 預設也會記完整網址，伺服器上就有兩份日誌躺著 token。
- **做法**：nginx 設定對 `/stream` 路徑的日誌遮掉 query string（自訂 `log_format` 或條件式關閉該路徑的 access_log）。

### 3. CORS 收緊（上正式環境前必做）

- **現況**：`backend/main.py` 設 `allow_origins=["*"]`，只適合開發測試（CLAUDE.md 已註記）。
- **做法**：改成列出前端的確切網址。

### 4. 事件判定 / 結案要記錄操作者（稽核追蹤）

- **現況**：`PATCH /events/{id}/verdict` 和 `/resolve` 都要求登入，但 `current_user` 只拿來擋權限（有沒有登入），判定/結案後**沒有存進資料庫**。`detect_events.staff_id` 是「被指派去處理的照護員」，跟「是哪個登入帳號按下判定/結案按鈕」是兩件事，目前完全沒記錄後者。
- **問題**：長照事件涉及院友安全，事後需要能回溯「這起事件是誰判定的、誰結案的、什麼時間點」，目前沒有這筆紀錄。
- **做法**：`detect_events` 加欄位記錄判定者/結案者的 `user_account.id` + 動作時間，或另外開一張操作紀錄表。
- **為什麼現在不做**：MVP 先把主流程做出來，稽核不影響功能可用性，先列入待辦。

## 架構 / 擴展

### 5. 多 worker 時，重推計時器與 SSE 連線池要改 Redis（衝流量開多 worker 前必做）

- **現況**：`backend/events/sse.py` 的連線池、`backend/events/service.py` 的 `watch_delivery` 重推計時器都存在單一程序的記憶體。
- **問題**：多 worker（`uvicorn --workers N`）時，事件與前端連線可能落在不同程序，計時器手上沒有另一程序的連線，重推送不到、送達狀態也各記各的。
- **做法**：連線池與跨程序訊息改用 Redis Pub/Sub 共享；計時器改用有共享狀態的排程（如 Redis-backed 或 APScheduler + Redis jobstore）。
- **為什麼現在不做**：作品集階段單一程序（`uvicorn --reload`）不受影響。

### 6. Kafka consumer 升級成「方案 D」（多台 web 或要水平擴充時必做）

- **現況**：`backend/kafka_consumer.py` 走**方案 B**——獨立行程讀 Kafka 後轉打 `POST /events`，由 FastAPI 行程自己 broadcast SSE。單機、單一 web 完全正常。
- **問題**：多台 web 時方案 B 會破——POST 只會進到其中一台，只有連在那台的前端收得到 SSE。
- **做法（業界標準正解）**：consumer 改為直接呼叫 `handle_incoming_event`，並把 `backend/events/sse.py` 的記憶體 `pool` 換成 **Redis Pub/Sub**，讓 broadcast 跨行程／跨機器（該檔 `pool` 定義處的註解已預告）。與上面第 5 項是同一個根因（記憶體 pool 不跨程序）、同一個解法（Redis Pub/Sub），屆時一起做。
- **為什麼現在不做**：作品集階段單機單 web，方案 B 正常運作；B 是 D 的墊腳石，consumer 主結構升級時幾乎不動。

### 7. `staff` 表停用，處理人改用 `user_account`（含刪除 `GET /staff`）

- **決定（2026-07-17）**：
  1. 不再維護 `staff` 表。照護員本來就是安養院員工、都有登入帳號，用 `user_account`
     一張表同時當通報人與事件處理人就夠，不需要兩套人員名單。
  2. **處理人＝按下判定按鈕的人**：`PATCH /events/{id}/verdict` 不再收 `staff_id`，
     處理人直接從 token 的 `sub` 拿。
  3. **刪除 `GET /staff`**：它的用途是「指派下拉選單的資料來源」，改成自己接手後沒有名單要挑。
- **與前端的落差（動工前要對齊）**：`frontend/src/hooks/EventsProvider.tsx` 的「接手」早就是
  「誰按誰接手」、沒有下拉選單，與決定 2 一致；但 `frontend/src/api/events.ts` 的註解顯示前端
  不知道 `GET /staff` 存在（畫面用「員工 #<id>」佔位），且前端還在等一個後端沒做的「接手」端點。
- **要改的地方**：
  - `detect_events.staff_id`：FK 從 `staff.staff_id` 改指 `user_account.id`，語意變成「處理人」
  - `backend/events/router.py`：刪 `GET /staff` 與 `Staff` import；`VerdictRequest` 拿掉 `staff_id`；
    verdict 改用 `current_user["sub"]` 查出 `user_account.id` 當處理人
  - `init_db.py`／`backend/tests/conftest.py`：不再種 `Staff` 資料
  - 測試：刪 `test_staff.py`；`test_verdict.py`／`test_resolve.py`／`test_models.py`／
    `test_delivery.py` 凡是帶 `staff_id` 的地方都要改
  - 舊 `staff` 表留著不刪——沒有程式讀它就不影響
- **待確認的業務問題**：護理站實際作業是「誰看到誰去處理」還是「值班的人指派別人去」？
  決定 2 假設是前者，動工前跟組長／前端同學確認。
- **與第 4 項的關係**：兩項會動到同一批欄位。真跌倒時「處理人」就是操作者，但誤報時不指派
  處理人、仍需記錄是誰判的誤報，兩者不完全重疊，屆時一起設計、只改一次事件表。
- **為什麼現在不做**：本輪先做帳號系統改版；事件流程目前運作正常，改動會牽動已驗收的功能。

## 帳號系統（2026-07 改版時記入，詳見 `superpowers/specs/2026-07-17-account-redesign-design.md`）

### 8. 軟刪除的復職端點

`is_active` 設 `False` 後沒有 API 能改回 `True`，只能進 DB 手改。做法：加 admin-only 的啟用端點。

### 9. 初始 admin 密碼改用環境變數

`init_db.py` 的 `seed_accounts` 把密碼 `123456` 寫死在程式碼裡。做法：改讀 `.env`。

### 10. 多租戶「選機構登入」

員編僅「機構內」唯一時，登入要多帶機構識別才查得到正確帳號。單機構 MVP 用不到。

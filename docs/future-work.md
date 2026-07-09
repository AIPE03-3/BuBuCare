# 未來強化清單

> 這裡記「現階段刻意不做、但上正式環境前要回頭做」的事項。
> 每項都寫清楚：為什麼現在不做、什麼時候該做。

## 安全強化

### 1. Refresh token + 短效 access token（上正式環境前必做）

- **現況**：單一 JWT，有效期 1 天（`auth.py` 的 `ACCESS_TOKEN_EXPIRE_DAYS`）。過期就要重新登入。
- **問題**：token 有效期長 + `/stream` 的 token 放在網址上會進伺服器日誌，等於日誌裡的 token 有一整天的冒用窗口。
- **做法**：改成兩張票——短效 access token（15~30 分鐘）+ 長效 refresh token（7~30 天，HttpOnly cookie 存放），前端在 access token 快過期時自動用 refresh token 換新的，使用者無感。
- **為什麼現在不做**：作品集階段、日誌都在自己伺服器上，風險可接受；refresh 機制要多做端點、前端邏輯和撤銷管理。

### 2. Nginx 日誌遮蔽 /stream 的 query 參數（架 nginx 時順手做）

- **現況**：`/stream?token=...` 的完整網址會被寫進存取日誌。目前只有 uvicorn 一份。
- **注意**：未來若在前面架 nginx（自架的算自家日誌，風險等級不變），nginx 預設也會記完整網址，伺服器上就有兩份日誌躺著 token。
- **做法**：nginx 設定對 `/stream` 路徑的日誌遮掉 query string（自訂 `log_format` 或條件式關閉該路徑的 access_log）。

### 3. CORS 收緊（上正式環境前必做）

- **現況**：`allow_origins=["*"]`，只適合開發測試（CLAUDE.md 已註記）。
- **做法**：改成列出前端的確切網址。

## 架構 / 擴展

### 5. 多 worker 時，重推計時器與 SSE 連線池要改 Redis（衝流量開多 worker 前必做）

- **現況**：`sse.py` 的連線池、`event_service.py` 的 `watch_delivery` 重推計時器都存在單一程序的記憶體。
- **問題**：多 worker（`uvicorn --workers N`）時，事件與前端連線可能落在不同程序，計時器手上沒有另一程序的連線，重推送不到、送達狀態也各記各的。
- **做法**：連線池與跨程序訊息改用 Redis Pub/Sub 共享；計時器改用有共享狀態的排程（如 Redis-backed 或 APScheduler + Redis jobstore）。
- **為什麼現在不做**：作品集階段單一程序（`uvicorn --reload`）不受影響。

### 6. Kafka consumer 升級成「方案 D」（多台 web 或要水平擴充時必做）

- **現況**：`kafka_consumer.py` 走**方案 B**——獨立行程讀 Kafka 後轉打 `POST /events`，由 FastAPI 行程自己 broadcast SSE。單機、單一 web 完全正常。
- **問題**：多台 web 時方案 B 會破——POST 只會進到其中一台，只有連在那台的前端收得到 SSE。
- **做法（業界標準正解）**：consumer 改為直接呼叫 `handle_incoming_event`，並把 `sse.py` 的記憶體 `pool` 換成 **Redis Pub/Sub**，讓 broadcast 跨行程／跨機器（`sse.py:32` 註解已預告）。與上面第 5 項是同一個根因（記憶體 pool 不跨程序）、同一個解法（Redis Pub/Sub），屆時一起做。
- **為什麼現在不做**：作品集階段單機單 web，方案 B 正常運作；B 是 D 的墊腳石，consumer 主結構升級時幾乎不動。

## 程式品質

### 4. 加 ruff linting（2026-06-29 舊計畫的未完成項）

- **現況**：專案沒有 linter，程式風格靠人工維持。
- **做法**：`uv add --dev ruff`，在 pyproject.toml 設定規則，跑 `ruff check .` 修完既有警告。

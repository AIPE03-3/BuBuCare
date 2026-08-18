# S3 事件畫面：讓前端看到影片/截圖

## Context（為什麼要做）

前端目前看不到事件的影片/截圖。原因：`detect_events.clip_path` / `snapshot_path` 這兩個欄位，
存的是 albert（AI 端）機器上的本機路徑，前端拿到打不開；`serialize_event` 也只是把這字串原封不動透傳。

albert 已確認：他會把影片上傳到 S3 bucket `aipe03-3`，並透過 Kafka 傳 **S3 URI**
（預設格式 `s3://aipe03-3/videos/filename.mp4`）。他還主動提議「後端拿 s3:// 後自己轉成 presigned URL」。

**目標**：後端把 `s3://...` 換成一張限時、可播放的 HTTPS 網址（presigned URL），
在前端真的要看影片時現發，bucket 全程保持私有（住民影像不公開）。albert 端無須改動。

## 方案（已與使用者確認）

- albert 傳 `s3://aipe03-3/videos/xxx.mp4`，後端原封不動存進 `clip_path` / `snapshot_path`（DB 存永久名牌、不會過期）。
- **新增專用端點 `GET /events/{id}/media`**：前端點開影片時才呼叫，後端當下用 boto3 換發 presigned URL 回傳。
  - 選這個而非「serialize 時一併換」：網址點開當下才生、保證新鮮不過期；事件列表 payload 也不用背一堆長網址。
- bucket 維持私有，不設公開讀取。

## 設計決策

- **presigned URL TTL**：預設 3600 秒（1 小時），做成可設定（env）。
- **只處理 `s3://` 開頭**：舊事件若存的是本機路徑，該欄回 `null`，端點不報錯。
- **region**：新增 `S3_REGION` env（`.env.example` 目前缺）。預設 `us-east-1`（`aipe03-3.s3.amazonaws.com`
  無 region 段通常是 us-east-1），**待與 albert 對齊確認實際 region**。
- **credentials**：`.env` 用的是 `ACCESS_KEY_ID` / `SECRET_ACCESS_KEY`（非 boto3 標準名），
  由 `config.py` 讀出、明確傳給 boto3 client。
- **不改** `serialize_event`：事件列表照舊，`clip_path` 原字串保留；影片網址一律走新端點。

## 要改的檔案

1. **`backend/core/config.py`** — 新增讀取：`S3_REGION`、`ACCESS_KEY_ID`、`SECRET_ACCESS_KEY`、
   `S3_URL_TTL`（選填、預設 3600）。維持「全 backend 唯一讀 .env 的地方」慣例。
2. **`.env.example`** — 補 `S3_REGION=us-east-1` 與 `S3_URL_TTL=3600`（bucket/keys 已有）。
3. **`backend/core/s3.py`（新檔）** — 橫切工具，比照 `core/database.py` 定位：
   - 建一個 boto3 S3 client（用 config 的 region + 明確帶入 access/secret key）。
   - `parse_s3_uri(uri) -> (bucket, key) | None`：只接受 `s3://` 開頭，其餘回 `None`。
   - `generate_presigned_url(s3_uri, expires=TTL) -> str | None`：解析→ `client.generate_presigned_url('get_object', ...)`；
     非 s3:// 或空字串回 `None`。
4. **`backend/events/router.py`** — 新增 `GET /events/{id}/media`（需登入，比照其他事件端點）：
   - 查不到事件 → 404。
   - 回 `{ "clip_url": <presigned|null>, "snapshot_url": <presigned|null> }`。
   - 用 `core/s3.generate_presigned_url` 換發；`snapshot_path` 為空或非 s3:// → `snapshot_url` 為 `null`。
5. **`backend/tests/`** — 新增測試（延用 conftest 的 in-memory SQLite；**stub 掉 boto3，不打真 AWS**）：
   - `parse_s3_uri` 正常 / 非 s3:// / 空字串。
   - 端點：正常回兩個 url、事件不存在回 404、snapshot 為 null 時 `snapshot_url` 為 null、
     clip 是本機舊路徑時 `clip_url` 為 null、未登入被擋。
6. **`CLAUDE.md`** — API 路由表補 `GET /events/{id}/media` 一列。

## 重用的既有東西

- 事件查詢 / 登入依賴：沿用 `backend/events/router.py` 既有的 `get_db`、登入依賴（`core/dependencies.py`）與
  `DetectEvent` 查法，不另造。
- 設定載入：集中在 `backend/core/config.py`（既有慣例，勿在別處讀 env）。
- boto3 已在 `pyproject.toml`（`boto3>=1.43.37`），無須新增依賴。

## 驗證方式（怎麼確認會動）

1. **單元測試**：`uv run pytest -v`（PowerShell 全新 session 用完整路徑
   `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest -v`），
   新測試全綠、既有測試不回歸。
2. **手動端到端**：在某事件的 `clip_path` 放一個真的 `s3://aipe03-3/videos/xxx.mp4`（albert 提供樣本），
   登入拿 token → `GET /events/{id}/media` → 拿回的 `clip_url` 用瀏覽器/curl 打得開、能播放；
   等 TTL 過後再打同一張舊網址應變成 AccessDenied（證明有上鎖 + 會過期）。
3. **region 對齊**：與 albert 確認 `aipe03-3` 實際 region，必要時改 `.env` 的 `S3_REGION`。

## 待辦相依（非後端本身，但要跟進）

- 跟 albert 確認：Kafka 訊息的 `clip_path` / `snapshot_path` 會是 `s3://aipe03-3/...` 格式、bucket 實際 region。
- 後端需拿到 `aipe03-3` bucket 的讀取權限 credentials（填進 `.env`）。

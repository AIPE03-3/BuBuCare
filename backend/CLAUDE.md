# fulilian-backend 專案說明

## 與使用者的合作規則（每次對話都必須遵守）

1. **動手前先說明、同意後才做**：每一步先用白話講清楚要改哪個檔案、改什麼、為什麼，等使用者看懂並同意才執行，不要自己連續執行多步
2. **解釋概念的方式**：先用生活比喻 → 再看實際程式碼 → 最後才帶術語名稱；使用者說看不懂就換更具體的方式重講，不要跳過（過去太快進術語，使用者常要追問第二次才懂）
3. 使用者是邊學邊做，他需要理解每一步在做什麼
4. **git commit 不要自己直接執行**：可以在適當時機「提醒」使用者要不要 commit，但實際 commit 由使用者決定
5. **每輪功能告一段落時，主動列出本輪產生 / 改動的檔案**，並標「建議保留」或「可刪除」，讓使用者決定，不要等他來問

---

## 專案概述

fulilian 是一套「YOLO 初篩 → VLM 精判 → 人工確認 → 閉環回訓」的安養院跌倒偵測系統。
本專案（fulilian-backend）是**通報層的 FastAPI 後端**，負責接收事件、推送通知、人工確認流程。

目前已實作：JWT 身分驗證、帳號管理（admin 開帳號 / 員編登入 / me / 改密碼 / admin 重設密碼 / 軟刪除）、admin / staff 角色分權、
跌倒事件通報 + SSE 推播 + 人工確認流程（判定/結案）、Kafka consumer（接 AI 端 Kafka，實接完成）、
Prometheus 指標輸出（`/metrics`，目前只有人工判定次數）。
使用 passlib + bcrypt 做密碼雜湊，PostgreSQL（AWS RDS）儲存資料。
事件功能的設計規格記錄於後端的內部設計文件。

### Kafka consumer（2026-07-10 實接完成）

接 AI 端 Kafka（albert 當 producer 打 topic `processed-reports`）。**方案 B**：獨立行程
`backend/kafka_consumer.py` 讀 topic → 轉打現成 `POST /events`（**不**直呼 `handle_incoming_event`——
獨立行程直呼會 broadcast 到自己的空 SSE pool、前端收不到）。設計規格見
後端的內部設計文件（Task 1-3 全部完成，含 Step 6 端到端煙霧測試手動驗證通過）。
（未來多台 web 要升級成「方案 D」的事項見 `backend/docs/future-work.md` 第 6 項。）

---

## 環境

- 套件管理：**uv**（2026-07-24 起 `pyproject.toml`/`uv.lock` 位於 `backend/`，uv 指令需在 backend/ 下執行）
- 虛擬環境：`backend/.venv`（於 backend/ 下 `uv sync` 建立）。根目錄舊 venv 已於 2026-07-30 刪除
- Python：3.12
- 資料庫連線資訊存在 `.env`（已加入 `.gitignore`，不會被 git 追蹤）

### 啟動服務

```bash
cd backend
uv run uvicorn main:app --reload
# 或 python -m uvicorn main:app --reload
```

> 2026-07-24 重構：`pyproject.toml`/`uv.lock` 已搬進 `backend/`，backend 自成一包。
> 所有 uv／啟動／測試指令一律**先 `cd backend`**；import 從 `backend.core.xxx` 改為 `core.xxx`。

> 註：`.venv` 於 2026-07-04 砍掉重建，已修好舊資料夾改名造成的 uv run trampoline bug，`uv run` 恢復正常。

### 第一次初始化資料庫（對 PostgreSQL 執行）

```bash
cd backend
python -m init_db
# 建表 → 種 demo 資料（公司/區域/裝置/照護員）→ 建帳號
# 帳號：A001 / 123456（admin）和 E001 / 123456（staff，陳雅文）
# 可重複執行：已存在的自動略過，不會報錯
```

> **不會**為既有表補欄位：`create_all` 只建「不存在的表」，改 models.py 的欄位後跑 init_db 不會生效。
> 既有表要加/改欄位，得手動 `ALTER TABLE`，或 `DROP TABLE` 後再跑 init_db 重建。

> 沒種子資料的話 `POST /events` 會查不到 device_id 而回 400，整個事件流程跑不動，新環境第一件事就是跑這支。

### 執行測試

```bash
cd backend
uv run pytest -v
# PowerShell 工具（全新 session、venv 沒啟動）改用完整路徑，且需在 backend/ 下執行：
# Push-Location backend; & "C:\Users\user\Projects\fulilian-backend\backend\.venv\Scripts\python.exe" -m pytest -v; Pop-Location
```

> 測試在 `backend/tests/`（pyproject 已在 backend/，`testpaths=["tests"]`，於 backend/ 下直接跑 `pytest` 就好）。

> 一定要用 `backend\.venv`，不是根目錄那個舊 `.venv`——舊的沒跟著 pyproject 更新，
> 少了 `prometheus_client` 之類的新相依，一跑就 `ModuleNotFoundError`。
> 全套跑完約 2 分 20 秒（SSE/送達確認的測試有等待），改單一功能時指定檔案跑比較快。

---

## 檔案結構

2026-07-13 重構：程式碼按**部署單位**切成 `backend/`（通報層）、`ai/`（判斷層，albert 負責）、
未來的 `frontend/`。backend 內部用 **feature-based**：一個資料夾＝一個完整功能。
兩邊零 Python import 相依，只透過 Kafka 溝通。

### backend/（通報層 FastAPI）

| 檔案                          | 功能                                                                   |
| ----------------------------- | ---------------------------------------------------------------------- |
| `backend/main.py`             | app 組裝點：建 app、設 CORS、掛 router（不含任何路由本體）              |
| `backend/kafka_consumer.py`   | 獨立行程：消費 Kafka topic `processed-reports`，轉打 `POST /events`     |
| `backend/init_db.py`          | 正式 DB 初始化：建表 + 種子資料 + 初始帳號（可重複執行；不補既有表欄位）|
| `backend/global-bundle.pem`   | AWS RDS SSL 憑證                                                       |
| `backend/core/config.py`      | **全 backend 唯一讀 .env 的地方**：DB / SECRET_KEY / API key / Kafka / S3 / MediaMTX / 串流權杖與 RTSP 帳密 |
| `backend/core/database.py`    | SQLAlchemy engine、SessionLocal、get_db                                 |
| `backend/core/models.py`      | 資料表定義（User + Company/Location/Device/Staff/DetectEvent）          |
| `backend/core/auth.py`        | JWT 產生與驗證                                                         |
| `backend/core/security.py`    | 密碼雜湊（hash）與比對（verify）                                       |
| `backend/core/dependencies.py`| 依賴注入：驗證 token、檢查 admin 角色                                   |
| `backend/users/router.py`     | 帳號 9 個端點（register / login / me / me/password / users / users/{id} / users/{id}/role / users/{id}/password / delete） |
| `backend/events/router.py`    | 事件 5 個端點 + SSE（APIRouter）                                        |
| `backend/events/service.py`   | 事件處理核心：handle_incoming_event（存 DB → 廣播）、watch_delivery     |
| `backend/events/sse.py`       | SSE 連線池（register/unregister/broadcast）                             |
| `backend/streams/router.py`   | 串流身分驗證：發 60 秒權杖 + 供 MediaMTX 驗票（兩個端點）               |
| `backend/observability/router.py` | 服務層級端點：`/health` 健康檢查、`/metrics` Prometheus 指標輸出     |

> `core/` 放跨功能共用的橫切關注；`users/`、`events/` 各自是一個完整功能。
> 新增功能（如 S3 影片、報表）＝新增一個資料夾，不是改一堆現有檔案。

### ai/（判斷層，albert 負責）

檔案內容原封不動從 repo root 平移進來。**相對路徑以 `ai/` 為基準，執行前先 `cd ai`。**
目前是 2026-07 舊版快照（YOLO），albert 的最新版（RT-DETR + ClearML）尚未上傳，
屆時在 `ai/` 內整包替換即可，`backend/` 不受影響。

### 其他

| 路徑                        | 功能                                             |
| --------------------------- | ------------------------------------------------ |
| `.env` / `.env.example`     | 環境變數（本體不進 git，範本進）                 |
| `docker-compose.yml`        | 四容器一鍵啟動：kafka / kafka-ui / backend / frontend |
| `DEPLOY.md`                 | 交付給組員的部署說明（含刻意加的防呆，改 compose 前先看） |
| `backend/tests/`            | backend 測試（conftest 用 in-memory SQLite）     |
| `backend/docs/`                   | backend 的文件（設計規格、驗收、未來強化清單）     |
| `backend/docs/future-work.md`     | 未來強化清單（上正式環境前必讀）                 |

---

## API 路由

| 方法   | 路徑                     | 權限                          | 說明                                                        |
| ------ | ------------------------ | ----------------------------- | ----------------------------------------------------------- |
| POST   | `/register`            | 需 admin                      | admin 開帳號：employee_id/full_name/role/password/email(選填)，回 201+新帳號資料 |
| POST   | `/login`               | 公開                          | 員編+密碼登入，回 JWT token 與 must_change_password；停用帳號回 401        |
| GET    | `/me`                  | 需登入                        | 回 employee_id / full_name / role（全來自 JWT，不查庫）                    |
| PATCH  | `/me/password`         | 需登入                        | 改自己的密碼（驗舊密碼），成功後 must_change_password 歸 False             |
| PATCH  | `/users/{id}/password` | 需 admin                      | admin 重設員工密碼，成功後 must_change_password 設 True                    |
| DELETE | `/users/{id}`          | 需 admin                      | 軟刪除（is_active=False）；不能停用自己                                    |
| POST   | `/events`              | X-API-Key                     | 判斷層送入新事件（status=pending），存 DB 後 SSE 廣播       |
| POST   | `/events/{id}/ack`     | 需登入                        | 前端收到 SSE 後回報送達，蓋 notified_at，回 {"status":"ok"} |
| GET    | `/stream`              | 需登入（token 放 query 參數） | SSE 長連線，推播 event_created / event_updated              |
| GET    | `/events`              | 需登入                        | 事件列表（新→舊，含裝置名稱/位置/通報階段/處理人姓名）      |
| PATCH  | `/events/{id}/verdict` | 需登入                        | 判定：誤報→直接結案；真跌倒→處理中；操作員（判定者）由後端從 JWT 自動記入 verdict_by（誤報同時記 resolved_by） |
| PATCH  | `/events/{id}/resolve` | 需登入                        | 結案（僅限處理中的事件）；結案者由後端從 JWT 自動記入 resolved_by |
| GET    | `/events/{id}/media`   | 需登入                        | 換發影片/截圖限時網址：把 clip_path/snapshot_path 的 `s3://` 現轉 presigned URL，回 `{clip_url, snapshot_url}`；非 s3:// 或空值回 null |
| GET    | `/devices`             | 需登入                        | 裝置（鏡頭）清單，JOIN locations 夾帶位置名稱/樓層；串流回兩種形式：`stream_channel`/`stream_channel_detect`（DB 原始頻道名，給 AI 端自己接 rtsp://）與 `stream_url`/`stream_url_detect`（後端現算的 WHEP 網址，給瀏覽器；`MEDIAMTX_BASE_URL` 或頻道名為空則回 null） |
| PATCH  | `/devices/{id}`        | 需 admin                      | 改鏡頭名稱（只收 device_name）                              |
| GET    | `/users`               | 需 admin                      | 使用者管理名單（只回未停用帳號，白名單四欄，不含密碼）     |
| PATCH  | `/users/{id}`          | 需 admin                      | 改使用者姓名（只收 full_name，不收 role/密碼）              |
| PATCH  | `/users/{id}/role`     | 需 admin                      | 改使用者角色（只收 role: staff/admin）；不能改自己（400）；對方**重新登入後才生效** |
| POST   | `/events/{id}/reports` | 需登入                        | 存一筆通報單（初報/續報/結報累積不覆蓋，created_by 由後端從 JWT 記） |
| GET    | `/events/{id}/reports` | 需登入                        | 查某事件全部通報單（排序：舊→新）                           |
| POST   | `/streams/{channel}/token` | 需登入                    | 發一張 60 秒串流權杖（綁死該頻道），前端拿去連 MediaMTX 看畫面 |
| POST   | `/streams/auth`        | **公開**（MediaMTX 呼叫）     | MediaMTX 驗票用：回 204 放行／401 擋下。瀏覽器走短命權杖；RTSP 讀取一律放行（受控內網前提） |
| GET    | `/health`              | **公開**                      | 健康檢查，回 `{"status":"ok"}`；不查資料庫。部署腳本 `gcp_vm_environment/deploy_dev.sh` 用它當探針 |
| GET    | `/metrics`             | **公開**                      | Prometheus 指標輸出（純文字非 JSON）。目前只有 `event_verdict_total{verdict}`＝人工判定次數 |

---

## 資料庫

- **資料表**：`user_account`（非 `users`）+ `companies`、`locations`、`devices`、`staff`、`detect_events`、`detect_event_reports`（已建立）
- **devices 串流欄位**：`stream_channel`（原味頻道名，如 `cam_in`）、`stream_channel_detect`（AI 畫框後的頻道名，
  如 `cam_out`，沒接 AI 為 NULL）。**存的是頻道名不是網址**——主機位址在 `.env` 的 `MEDIAMTX_BASE_URL`，
  換場地只改該值即可。兩欄原名 `stream_url`/`stream_url_detect`，因名稱誤導（有人照名字填入完整 RTSP 網址）
  於 2026-07-28 改為現名
- **detect_event_reports 欄位**：`report_id`（自動編號 PK）、`event_id`（FK→detect_events）、
  `report_type`（Enum initial/follow_up/final）、`form`（JSON，整包表單原樣保管，定義權在前端）、
  `created_by`（FK→user_account.employee_id，誰存的誰負責）、`created_at`；每次存都是新的一筆，不覆蓋
- **事件帶通報階段**：`serialize_event` 回 `report_stage`（最新一筆通報單的 `report_type`）與
  `last_report_at`，來源是 `DetectEvent.reports` 關聯（無新增欄位）。列表查詢用 `selectinload` 避免 N+1
- **user_account 欄位**：`id`、`employee_id`（unique，登入用員編）、`full_name`、`password`、
  `email`（選填, unique）、`role`（Enum staff/admin）、`must_change_password`、`is_active`、
  `last_login_time`、`company_id`（not null, default 1）
- **位置凍結**：`locations` 新增 `floor`（nullable）；`detect_events` 新增 `location_id`（FK→locations, nullable）
- **操作員記錄**：`detect_events` 的 `verdict_by`（判定者）、`resolved_by`（結案者）皆為 `String(50)`、nullable、
  FK→`user_account.employee_id`；由後端從 JWT 自動填入按按鈕的員編（誰點的誰負責），前端不帶。已無 `staff_id`
- **處理人顯示姓名**：`serialize_event` 另回 `verdict_by_name` / `resolved_by_name`（純顯示，**不新增資料表欄位**）。
  名字像 `device` 一樣由呼叫端事先查好再傳入、`serialize_event` 只組裝：列表端用 `aliased(User)` 雙 `outerjoin`
  一次撈（避免 N+1）、單筆端（判定/結案）用 `service.operator_names(db, event)` 取。前端查不到姓名時退回顯示員編
- **ENUM 欄位**：status/verdict 用原生 SQLAlchemy `Enum` + `create_constraint=True`
  （PostgreSQL 真 ENUM、SQLite 測試環境 CHECK 約束；程式端讀寫仍是字串）
- **SSL**：連線時使用 `global-bundle.pem`，sslmode=verify-full
- **測試時**：`conftest.py` 用記憶體 SQLite，與 PostgreSQL 完全隔離

---

## 注意事項

- **bcrypt 版本**：鎖定 `4.0.1`（pyproject.toml），不能升級，升到 5.x 會導致 passlib 初始化爆炸
- **PowerShell 工具**：每次呼叫都是全新 session，不繼承已啟動的 venv，需用完整路徑（見「執行測試」）
- **SECRET_KEY**：已移到 `.env`，`auth.py` 用 `os.environ["SECRET_KEY"]` 讀取，不再 hardcode
- **兩種 JWT 靠 `scope` 區分**：登入 token（1 天）與串流權杖（60 秒，帶 `scope=stream`）
  用同一把 `SECRET_KEY` 簽，外觀分不出來，故**兩邊門口都檢查**——`/streams/auth` 拒絕沒有
  `scope` 的登入 token，`get_current_user` 拒絕帶 `scope=stream` 的串流權杖。改動 JWT 內容時
  兩處都要顧
- **串流要先起後端**：MediaMTX 開了 `authMethod: http`，每個觀看請求都回頭問後端。
  後端沒起來 → 畫面全黑。退路是把 `mediamtx.yml` 的三個 auth 設定註解掉重啟（見 `streaming/README.md`）
- **Prometheus 指標的三個坑**：①指標（Counter）定義在**它量測的功能**檔案裡（如 `events/router.py`
  的 `EVENT_VERDICT_TOTAL`），`/metrics` 只是輸出窗口，靠 prometheus_client 的全域登記簿取值，
  **不需互相 import**；②`.inc()` 要放 `db.commit()` **之後**，放前面則 commit 失敗會讓指標虛高、
  永遠對不回 DB；③帶標籤的指標「第一次用到才誕生」——後端重啟後還沒人按過判定，`/metrics` 裡
  **不會有那一列**（不是顯示 0）
- **CORS**：目前 `allow_origins=["*"]`，僅適合開發測試
- **未來強化清單**：`backend/docs/future-work.md`——上正式環境前要做的事（refresh token、nginx 日誌遮蔽、CORS 收緊）

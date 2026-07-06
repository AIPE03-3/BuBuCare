# fulilian-backend 專案說明

## 與使用者的合作規則（每次對話都必須遵守）

1. **動手前先說明、同意後才做**：每一步先用白話講清楚要改哪個檔案、改什麼、為什麼，等使用者看懂並同意才執行，不要自己連續執行多步
2. **解釋概念的方式**：先用生活比喻 → 再看實際程式碼 → 最後才帶術語名稱；使用者說看不懂就換更具體的方式重講，不要跳過（過去太快進術語，使用者常要追問第二次才懂）
3. 使用者是邊學邊做，他需要理解每一步在做什麼
4. **git commit 不要自己直接執行**：可以在適當時機「提醒」使用者要不要 commit，但實際 commit 由使用者決定（已有 `.claude/` hook 會攔截確認）
5. **每輪功能告一段落時，主動列出本輪產生 / 改動的檔案**，並標「建議保留」或「可刪除」，讓使用者決定，不要等他來問

---

## 專案概述

fulilian 是一套「YOLO 初篩 → VLM 精判 → 人工確認 → 閉環回訓」的安養院跌倒偵測系統。
本專案（fulilian-backend）是**通報層的 FastAPI 後端**，負責接收事件、推送通知、人工確認流程。

目前已實作：JWT 身分驗證、帳號管理（register / login / me / delete）、admin / staff 角色分權、
跌倒事件通報 + SSE 推播 + 人工確認流程（判定/結案）。
使用 passlib + bcrypt 做密碼雜湊，PostgreSQL（AWS RDS）儲存資料。
事件功能的設計規格見 `docs/superpowers/specs/2026-07-02-event-sse-design.md`。

---

## 環境

- 套件管理：**uv**
- 虛擬環境：`.venv`，啟動後前綴顯示 `(fulilian-backend)`
- Python：3.12
- 資料庫連線資訊存在 `.env`（已加入 `.gitignore`，不會被 git 追蹤）

### 啟動服務

```bash
uv run uvicorn main:app --reload
# 或 python -m uvicorn main:app --reload
```

> 註：`.venv` 於 2026-07-04 砍掉重建，已修好舊資料夾改名造成的 uv run trampoline bug，`uv run` 恢復正常。

### 第一次建立初始帳號（對 PostgreSQL 執行）

```bash
python create_test_user.py
# 建立 admin / 123456（admin）和 staff01 / 123456（staff）
# 已有帳號自動略過，不會報錯
```

### 執行測試

```bash
uv run pytest tests/ -v
# PowerShell 工具（全新 session、venv 沒啟動）改用完整路徑：
# & "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/ -v
```

---

## 檔案結構

| 檔案                                     | 功能                                                                         |
| ---------------------------------------- | ---------------------------------------------------------------------------- |
| `main.py`                              | FastAPI 路由主體（register / login / me / delete）                           |
| `auth.py`                              | JWT 產生與驗證                                                               |
| `security.py`                          | 密碼雜湊（hash）與比對（verify）                                             |
| `dependencies.py`                      | 依賴注入：驗證 token、檢查 admin 角色                                        |
| `database.py`                          | SQLAlchemy 連線設定（讀 .env，連 PostgreSQL）                                |
| `models.py`                            | 資料表定義（User + Company/Location/Device/Staff/DetectEvent）               |
| `sse.py`                               | SSE 連線池（register/unregister/broadcast）                                  |
| `event_service.py`                     | 事件處理核心：handle_incoming_event（存 DB → 廣播）                         |
| `event_routes.py`                      | 事件相關 6 個端點（APIRouter）                                               |
| `create_test_user.py`                  | 建立初始帳號的腳本（admin + staff01）                                        |
| `create_seed_data.py`                  | 正式 DB 初始化：建新表 + user_account 加 company_id + 種子資料（可重複執行） |
| `index.html`                           | 純 HTML/JS 前端測試介面                                                      |
| `.env`                                 | DB 連線資訊 + SECRET_KEY（不進 git）                                         |
| `.env.example`                         | 環境變數範本（進 git，不含真實值）                                           |
| `global-bundle.pem`                    | AWS RDS SSL 憑證                                                             |
| `tests/conftest.py`                    | 測試共用 fixtures（in-memory SQLite）                                        |
| `tests/test_*.py`                      | 各端點 / 模型 / SSE 的測試（依檔名對應功能）                                 |
| `docs/future-work.md`                  | 未來強化清單（上正式環境前必讀）                                             |
| `docs/superpowers/specs/`              | 正式設計規格（spec），實作以這裡為準                                         |
| `docs/event-sse-discussion-handoff.md` | 事件 + SSE 功能的討論過程紀錄                                                |

---

## API 路由

| 方法   | 路徑                     | 權限                          | 說明                                                      |
| ------ | ------------------------ | ----------------------------- | --------------------------------------------------------- |
| POST   | `/register`            | 公開                          | 註冊新帳號，需要 username/email/password，預設 role=staff |
| POST   | `/login`               | 公開                          | 登入，回傳 JWT token                                      |
| GET    | `/me`                  | 需登入                        | 查看自己的帳號和角色                                      |
| DELETE | `/users/{id}`          | 需 admin                      | 刪除指定 ID 的使用者                                      |
| POST   | `/events`              | X-API-Key                     | 判斷層送入新事件（status=pending），存 DB 後 SSE 廣播     |
| GET    | `/stream`              | 需登入（token 放 query 參數） | SSE 長連線，推播 event_created / event_updated            |
| GET    | `/events`              | 需登入                        | 事件列表（新→舊，含裝置名稱/位置）                       |
| GET    | `/staff`               | 需登入                        | 照護員名單（指派下拉選單用）                              |
| PATCH  | `/events/{id}/verdict` | 需登入                        | 判定：誤報→直接結案；真跌倒（必帶 staff_id）→處理中     |
| PATCH  | `/events/{id}/resolve` | 需登入                        | 結案（僅限處理中的事件）                                  |

---

## 資料庫

- **資料表**：`user_account`（非 `users`）+ `companies`、`locations`、`devices`、`staff`、`detect_events`（已建立）
- **user_account 欄位**：`id`、`name`、`password`、`email`、`role`、`last_login_time`、`company_id`（not null, default 1）
- **位置凍結**：`locations` 新增 `floor`（nullable）；`detect_events` 新增 `location_id`（FK→locations, nullable）
- **ENUM 欄位**：status/verdict/severity 用原生 SQLAlchemy `Enum` + `create_constraint=True`
  （PostgreSQL 真 ENUM、SQLite 測試環境 CHECK 約束；程式端讀寫仍是字串）
- **SSL**：連線時使用 `global-bundle.pem`，sslmode=verify-full
- **測試時**：`conftest.py` 用記憶體 SQLite，與 PostgreSQL 完全隔離

---

## 注意事項

- **bcrypt 版本**：鎖定 `4.0.1`（pyproject.toml），不能升級，升到 5.x 會導致 passlib 初始化爆炸
- **PowerShell 工具**：每次呼叫都是全新 session，不繼承已啟動的 venv，需用完整路徑（見「執行測試」）
- **SECRET_KEY**：已移到 `.env`，`auth.py` 用 `os.environ["SECRET_KEY"]` 讀取，不再 hardcode
- **CORS**：目前 `allow_origins=["*"]`，僅適合開發測試
- **未來強化清單**：`docs/future-work.md`——上正式環境前要做的事（refresh token、nginx 日誌遮蔽、CORS 收緊）

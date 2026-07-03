# fulilian-backend 專案說明

## 與使用者的合作規則（每次對話都必須遵守）

1. **每一步動手前先說明**：要改哪個檔案、改什麼、為什麼，用白話說明，不用術語
2. **等使用者看懂並同意後才執行**，不要自己連續執行多步
3. **如果使用者說看不懂**，換更具體的方式解釋，不要跳過
4. 使用者是邊學邊做，他需要理解每一步在做什麼

---

## 專案概述

fulilian 是一套「YOLO 初篩 → VLM 精判 → 人工確認 → 閉環回訓」的安養院跌倒偵測系統。
本專案（fulilian-backend）是**通報層的 FastAPI 後端**，負責接收事件、推送通知、人工確認流程。

目前已實作：JWT 身分驗證、帳號管理（register / login / me / delete）、admin / staff 角色分權。
使用 passlib + bcrypt 做密碼雜湊，PostgreSQL（AWS RDS）儲存帳號資料。

**進行中**：跌倒事件通報 + SSE 推播 + 人工確認流程。設計已定案、尚未實作，
正式規格見 `docs/superpowers/specs/2026-07-02-event-sse-design.md`（實作前必讀）。

---

## 環境

- 套件管理：**uv**
- 虛擬環境：`.venv`，啟動後前綴顯示 `(login_test)`（舊名稱，正常現象）
- Python：3.12
- 資料庫連線資訊存在 `.env`（已加入 `.gitignore`，不會被 git 追蹤）

### 啟動服務

`uv run` 在這台機器有 trampoline 路徑問題，改用：

```bash
python -m uvicorn main:app --reload
```

### 第一次建立初始帳號（對 PostgreSQL 執行）

```bash
python create_test_user.py
# 建立 admin / 123456（admin）和 staff01 / 123456（staff）
# 已有帳號自動略過，不會報錯
```

### 執行測試

```bash
& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/ -v
```

---

## 檔案結構

| 檔案                    | 功能                                               |
| ----------------------- | -------------------------------------------------- |
| `main.py`             | FastAPI 路由主體（register / login / me / delete） |
| `auth.py`             | JWT 產生與驗證                                     |
| `security.py`         | 密碼雜湊（hash）與比對（verify）                   |
| `dependencies.py`     | 依賴注入：驗證 token、檢查 admin 角色              |
| `database.py`         | SQLAlchemy 連線設定（讀 .env，連 PostgreSQL）      |
| `models.py`           | User 資料表定義（對應 `user_account` 表）          |
| `create_test_user.py` | 建立初始帳號的腳本（admin + staff01）              |
| `index.html`          | 純 HTML/JS 前端測試介面                            |
| `.env`                | DB 連線資訊 + SECRET_KEY（不進 git）               |
| `.env.example`        | 環境變數範本（進 git，不含真實值）                 |
| `global-bundle.pem`   | AWS RDS SSL 憑證                                   |
| `tests/conftest.py`   | 測試共用 fixtures（in-memory SQLite）              |
| `tests/test_login.py` | POST /login 測試（5 個）                           |
| `tests/test_register.py` | POST /register 測試（4 個）                     |
| `tests/test_me.py`    | GET /me 測試（3 個）                               |
| `tests/test_admin.py` | DELETE /users/{id} 測試（4 個）                    |
| `fulilian_schema.md.md` | 資料庫 schema 草稿（5 張表，spec 已修訂部分欄位） |
| `docs/superpowers/specs/` | 正式設計規格（spec），實作以這裡為準            |
| `docs/event-sse-discussion-handoff.md` | 事件 + SSE 功能的討論過程紀錄       |

---

## API 路由

| 方法   | 路徑            | 權限     | 說明                                  |
| ------ | --------------- | -------- | ------------------------------------- |
| POST   | `/register`   | 公開     | 註冊新帳號，需要 username/email/password，預設 role=staff |
| POST   | `/login`      | 公開     | 登入，回傳 JWT token                  |
| GET    | `/me`         | 需登入   | 查看自己的帳號和角色                  |
| DELETE | `/users/{id}` | 需 admin | 刪除指定 ID 的使用者                  |

事件相關 6 個端點（POST /events、GET /stream、GET /events、GET /staff、PATCH verdict/resolve）
已完成設計、尚未實作，規格見 spec。

---

## 資料庫

- **資料表**：`user_account`（非 `users`）
- **欄位**：`id`、`name`、`password`、`email`、`role`、`last_login_time`
- **規劃中**（spec 已定案）：新增 `companies`、`locations`、`devices`、`staff`、`detect_events` 五張表；
  `user_account` 加 `company_id`（not null, default 1）
- **SSL**：連線時使用 `global-bundle.pem`，sslmode=verify-full
- **測試時**：`conftest.py` 用記憶體 SQLite，與 PostgreSQL 完全隔離

---

## 注意事項

- **bcrypt 版本**：鎖定 `4.0.1`（pyproject.toml），不能升級，升到 5.x 會導致 passlib 初始化爆炸
- **uv run 問題**：這台機器的 `uv run` 有 trampoline 路徑 bug，一律改用 `python -m` 或完整路徑執行
- **PowerShell 工具**：每次呼叫都是全新 session，不繼承已啟動的 venv，需用完整路徑：`& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe"`
- **SECRET_KEY**：已移到 `.env`，`auth.py` 用 `os.environ["SECRET_KEY"]` 讀取，不再 hardcode
- **CORS**：目前 `allow_origins=["*"]`，僅適合開發測試
- **未來強化清單**：`docs/future-work.md`——上正式環境前要做的事（refresh token、nginx 日誌遮蔽、CORS 收緊）

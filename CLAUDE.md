# fulilian-backend 專案說明

## 與使用者的合作規則（每次對話都必須遵守）

1. **每一步動手前先說明**：要改哪個檔案、改什麼、為什麼，用白話說明，不用術語
2. **等使用者看懂並同意後才執行**，不要自己連續執行多步
3. **如果使用者說看不懂**，換更具體的方式解釋，不要跳過
4. 使用者是邊學邊做，他需要理解每一步在做什麼

---

## 專案概述

FastAPI + PostgreSQL（AWS RDS）的登入系統，使用 JWT 做身分驗證，passlib + bcrypt 做密碼雜湊。使用者分兩種角色：`admin`（管理員）和 `staff`（一般員工）。

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

### 執行腳本

```bash
python <檔案名稱>.py
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
| `.env`                | 資料庫連線資訊（不進 git）                         |
| `global-bundle.pem`   | AWS RDS SSL 憑證                                   |

---

## API 路由

| 方法   | 路徑            | 權限     | 說明                                  |
| ------ | --------------- | -------- | ------------------------------------- |
| POST   | `/register`   | 公開     | 註冊新帳號，需要 username/email/password，預設 role=staff |
| POST   | `/login`      | 公開     | 登入，回傳 JWT token                  |
| GET    | `/me`         | 需登入   | 查看自己的帳號和角色                  |
| DELETE | `/users/{id}` | 需 admin | 刪除指定 ID 的使用者                  |

---

## 資料庫

- **資料表**：`user_account`（非 `users`）
- **欄位**：`id`、`name`、`password`、`email`、`role`、`last_login_time`
- **SSL**：連線時使用 `global-bundle.pem`，sslmode=verify-full
- **測試時**：`conftest.py` 用記憶體 SQLite，與 PostgreSQL 完全隔離

---

## 注意事項

- **bcrypt 版本**：鎖定 `4.0.1`（pyproject.toml），不能升級，升到 5.x 會導致 passlib 初始化爆炸
- **uv run 問題**：這台機器的 `uv run` 有 trampoline 路徑 bug，一律改用 `python -m` 或完整路徑執行
- **PowerShell 工具**：每次呼叫都是全新 session，不繼承已啟動的 venv，需用完整路徑：`& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe"`
- **SECRET_KEY**：`auth.py` 裡是假字串，正式上線前必須換成隨機長字串
- **CORS**：目前 `allow_origins=["*"]`，僅適合開發測試

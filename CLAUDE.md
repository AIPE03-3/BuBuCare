# login_test 專案說明

## 專案概述

FastAPI + SQLite 的登入系統，使用 JWT 做身分驗證，passlib + bcrypt 做密碼雜湊。使用者分兩種角色：`admin`（管理員）和 `staff`（一般員工）。

## 環境

- 套件管理：**uv**（不是 pip，不是 venv）
- 虛擬環境：`.venv` 資料夾，啟動後顯示 `(login_test)` 前綴
- Python：3.12

### 啟動服務

```bash
uv run uvicorn main:app --reload
```

### 執行腳本

```bash
uv run python <檔案名稱>.py
```

### 第一次建立測試帳號

```bash
uv run python create_test_user.py
# 建立 admin / 123456，已有帳號會自動略過不會報錯
```

---

## 檔案結構

| 檔案                    | 功能                                               |
| ----------------------- | -------------------------------------------------- |
| `main.py`             | FastAPI 路由主體（register / login / me / delete） |
| `auth.py`             | JWT 產生與驗證                                     |
| `security.py`         | 密碼雜湊（hash）與比對（verify）                   |
| `dependencies.py`     | 依賴注入：驗證 token、檢查 admin 角色              |
| `database.py`         | SQLAlchemy 資料庫連線設定                          |
| `models.py`           | User 資料表定義                                    |
| `create_test_user.py` | 建立初始測試帳號的腳本                             |
| `index.html`          | 純 HTML/JS 前端測試介面                            |

---

## API 路由

| 方法   | 路徑            | 權限     | 說明                        |
| ------ | --------------- | -------- | --------------------------- |
| POST   | `/register`   | 公開     | 註冊新帳號，預設 role=staff |
| POST   | `/login`      | 公開     | 登入，回傳 JWT token        |
| GET    | `/me`         | 需登入   | 查看自己的帳號和角色        |
| DELETE | `/users/{id}` | 需 admin | 刪除指定 ID 的使用者        |

---

## 遇到的 Bug 與修正記錄

### Bug 1：bcrypt 版本衝突（最重要）

**症狀**：`ValueError: password cannot be longer than 72 bytes`，登入時 500 Internal Server Error

**根本原因**：uv 安裝了 bcrypt 5.0.0，passlib 1.7.4 在初始化時會用超過 72 bytes 的字串做內部測試，bcrypt 4.0 以後嚴格拒絕超過 72 bytes，導致爆炸。

**修正方式**：把 `.venv` 裡的 bcrypt 鎖定在 4.0.1

```bash
.venv\Scripts\python.exe -m ensurepip
.venv\Scripts\python.exe -m pip install bcrypt==4.0.1
```

pyproject.toml 已鎖定 `bcrypt==4.0.1`，之後 `uv sync` 不會升回去。

**下次注意**：新環境裝完套件後，bcrypt 版本一定要確認是 4.0.1，不能讓 uv 自動裝最新版。

---

### Bug 2：`declarative_base` 路徑棄用

**症狀**：啟動時出現 `DeprecationWarning`

**修正**：`database.py` 第 3 行

```python
# 改前
from sqlalchemy.ext.declarative import declarative_base
# 改後
from sqlalchemy.orm import declarative_base
```

---

### Bug 3：`create_test_user.py` 執行第二次會崩潰

**症狀**：`UNIQUE constraint failed: users.username`

**修正**：在建立前先查資料庫有沒有同名帳號，有的話略過

```python
existing = db.query(User).filter(User.username == "admin").first()
if existing:
    print("帳號已存在，略過建立")
else:
    # 建立帳號...
```

---

### Bug 4：我自己的診斷錯誤（提醒未來的 Claude）

PowerShell 工具每次呼叫都是全新 session，**不會繼承使用者已啟動的虛擬環境**。

所以在 PowerShell 工具裡跑 `python`，用的是系統 Python，不是 `.venv` 裡的 Python。

這導致我誤判「`(login_test)` 和 `.venv` 是兩個不同環境」，其實是同一個。uv 建立的虛擬環境啟動後，前綴顯示的是**專案資料夾名稱**，不是 `.venv`。

**正確做法**：在 PowerShell 工具裡要明確用完整路徑執行：

```bash
& "C:\Users\user\login_test\.venv\Scripts\python.exe" <指令>
```

---

## 設計決策

- **JWT 有效期**：1 天（`auth.py` 的 `ACCESS_TOKEN_EXPIRE_DAYS`）
- **密碼不存明文**：只存 bcrypt 雜湊後的結果
- **CORS**：目前設定 `allow_origins=["*"]`，允許所有來源，僅適合開發測試
- **角色**：只有兩級，`admin` 可刪除使用者，`staff` 只能查看自己
- **SECRET_KEY**：`auth.py` 裡的 `SECRET_KEY` 是預設的假字串，正式環境一定要換成隨機長字串


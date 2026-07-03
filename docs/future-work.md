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

## 程式品質

### 4. 加 ruff linting（2026-06-29 舊計畫的未完成項）

- **現況**：專案沒有 linter，程式風格靠人工維持。
- **做法**：`uv add --dev ruff`，在 pyproject.toml 設定規則，跑 `ruff check .` 修完既有警告。

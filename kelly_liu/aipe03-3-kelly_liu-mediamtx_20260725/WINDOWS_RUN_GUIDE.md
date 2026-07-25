# Windows PowerShell 執行方式

需求：Python 3.12、Node.js LTS、npm、MediaMTX。

## 1. 安裝並啟動後端

在專案根目錄開啟第一個 PowerShell：

```powershell
cd "你的路徑\aipe03-3-kelly_liu-mediamtx-jwt"

py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Copy-Item .env.example .env
notepad .env
```

請至少正確填寫 `.env` 的資料庫連線、`SECRET_KEY`、攝影機帳密，以及
`MEDIAMTX_PUBLISH_USER`、`MEDIAMTX_PUBLISH_PASS`。

啟動後端：

```powershell
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

後端文件：http://127.0.0.1:8000/docs

## 2. 安裝並啟動前端

在第二個 PowerShell：

```powershell
cd "你的路徑\aipe03-3-kelly_liu-mediamtx-jwt\frontend"

Copy-Item .env.example .env
notepad .env

npm install
npm run dev
```

開啟終端機顯示的網址，通常是：http://127.0.0.1:5173/

## 3. 啟動 MediaMTX

由範本建立真實設定：

```powershell
cd "你的路徑\aipe03-3-kelly_liu-mediamtx-jwt"
Copy-Item .\mediamtx\mediamtx-local.yml.example .\mediamtx\mediamtx-local.yml
notepad .\mediamtx\mediamtx-local.yml
```

如果 MediaMTX 是直接在 Windows 執行（不是 Docker），把：

```yaml
authHTTPAddress: http://host.docker.internal:8000/streams/auth
```

改成：

```yaml
authHTTPAddress: http://127.0.0.1:8000/streams/auth
```

將 MediaMTX 的執行檔放在專案根目錄後執行：

```powershell
.\mediamtx.exe .\mediamtx\mediamtx-local.yml
```

## 4. 測試

後端：

```powershell
cd "你的路徑\aipe03-3-kelly_liu-mediamtx-jwt"
.\.venv\Scripts\Activate.ps1
$env:SKIP_DB_INIT = "1"
python -m pytest backend\tests\test_streams.py -q
```

前端 production build：

```powershell
cd "你的路徑\aipe03-3-kelly_liu-mediamtx-jwt\frontend"
npm run build
```

## 注意

- `requirements.txt` 只管理 Python 後端套件。
- React/Vite 前端套件由 `frontend/package.json` 管理，所以仍需執行 `npm install`。
- MediaMTX 是獨立的 Go 執行檔，不是 Python 套件，不能寫進 `requirements.txt`。
- 三個服務都啟動後，登入前端並進入「即時監控」，點擊線上攝影機即可測試。

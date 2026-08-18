# main_D_20260810 完整版操作手冊

本版本以 `main_20260803` 的前後端與警告通知為基底，合入 Albert 版本的 DeepStream 骨架偵測、座標橋接與前端骨架疊圖。

以下命令以 Windows PowerShell 為主。Triton 與 DeepStream 腳本是 Bash，範例使用 WSL 執行。

## 0. 必要軟體

- Docker Desktop（啟用 WSL2 與 NVIDIA GPU 支援）
- NVIDIA Driver、NVIDIA Container Toolkit
- WSL2
- MediaMTX Windows 執行檔 `mediamtx.exe`
- 如需用影片模擬攝影機：FFmpeg

確認工具：

```powershell
docker version
wsl --status
nvidia-smi
ffmpeg -version
```

## 1. 關閉舊專案

先關閉 `main_20260803` 的 Compose 服務：

```powershell
Set-Location C:\AIPE_PROJECT\DeepStream_20260805\main_20260803\aipe03-3
docker compose down
```

如果之前啟動過 Albert 版本，也執行：

```powershell
Set-Location C:\AIPE_PROJECT\DeepStream_20260805\Albertchiang40210_20260803\aipe03-3
docker compose down
```

停止可能由腳本獨立建立的 Triton 與 DeepStream 容器：

```powershell
docker rm -f nh-triton nh-deepstream-pose-multi 2>$null
301..304 | ForEach-Object { docker rm -f "nh-deepstream-pose-$_" 2>$null }
```

MediaMTX 若是在另一個 PowerShell 視窗前景執行，切到該視窗按 `Ctrl+C`。不要執行 `docker compose down -v`，避免刪除資料卷。

確認舊容器已關閉：

```powershell
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

## 2. 建立新版環境設定

### 使用 Windows PowerShell

```powershell
Set-Location C:\AIPE_PROJECT\DeepStream_20260805\main_D_20260810\aipe03-3
Copy-Item .env.example .env
notepad .env
```

### 使用 WSL / Bash

如果提示字元像 `aipe@電腦名稱:/mnt/c/...$`，請使用這組命令：

```bash
cd /mnt/c/AIPE_PROJECT/DeepStream_20260805/main_D_20260810/aipe03-3
cp -n .env.example .env
notepad.exe .env
```

`cp -n` 在 `.env` 已存在時不會覆蓋它。若 `notepad.exe` 無法使用，可改用：

```bash
nano .env
```

在 nano 中按 `Ctrl+O`、Enter 儲存，再按 `Ctrl+X` 離開。

至少要把下列值改成真實設定，不能保留 `your-*` 或 `change-me-*`：

```dotenv
DB_USER=資料庫帳號
DB_PASSWORD=資料庫密碼
DB_HOST=資料庫主機
DB_PORT=5432
DB_NAME=資料庫名稱
DB_SSLMODE=disable
SECRET_KEY=至少32字元的隨機字串
EVENT_API_KEY=另一組足夠長的隨機字串
MEDIAMTX_BASE_URL=http://本機區網IP:8889
```

`EVENT_API_KEY` 同時供後端與 `detection-bridge` 使用，兩者必須一致。`.env` 含密碼，請勿提交或傳給他人。

本地 PostgreSQL 必須設定 `DB_SSLMODE=disable`；只有 AWS RDS 正式環境才使用 `DB_SSLMODE=verify-full`。

## 3. 啟動前後端、Kafka 與座標橋接

必須在新版根目錄執行，這會建立 `aipe03-3_default` Docker network：

```powershell
Set-Location C:\AIPE_PROJECT\DeepStream_20260805\main_D_20260810\aipe03-3
docker compose up -d --build
docker compose ps
```

追蹤啟動紀錄：

```powershell
docker compose logs -f backend frontend detection-bridge
```

看到服務穩定後按 `Ctrl+C` 只會離開紀錄畫面，不會停止容器。

## 3.1 初始化本地 PostgreSQL

第一次使用新的本地資料庫時，必須在 backend 容器內執行初始化。這會建立資料表、示範公司、區域、301–304 攝影機及初始登入帳號；重複執行不會重複新增。

建議直接執行完整自動檢查與初始化腳本：

```bash
cd /mnt/c/AIPE_PROJECT/DeepStream_20260805/main_D_20260810/aipe03-3
bash scripts/init_local_db.sh
```

腳本會自動檢查 `.env`、啟動 PostgreSQL、驗證帳密、重建完整 Compose（包含 frontend/backend）、執行 `init_db` 並用 `A001` 測試登入。以下保留手動步驟供故障排除。

先確認 PostgreSQL 與 backend 正在執行：

```bash
docker ps --filter name=nh-postgres
docker compose ps backend
```

若 `nh-postgres` 是停止狀態：

```bash
docker start nh-postgres
docker exec nh-postgres pg_isready
```

修改 `.env` 或加入 `DB_SSLMODE=disable` 後必須重建 backend，接著執行初始化：

```bash
cd /mnt/c/AIPE_PROJECT/DeepStream_20260805/main_D_20260810/aipe03-3
docker compose up -d --build backend
docker compose exec backend uv run --no-sync python -m init_db
```

正常結尾應顯示 `初始化完成`。初始登入帳號：

```text
管理員：A001 / 123456
照護員：E001 / 123456
```

直接測試後端登入 API：

```bash
curl -i -X POST http://127.0.0.1:8000/login \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data 'username=A001&password=123456'
```

成功時應回傳 `HTTP/1.1 200 OK` 與 `access_token`。若初始化失敗，查看：

```bash
docker compose logs --tail 200 backend
docker logs --tail 100 nh-postgres
```

## 4. 啟動 MediaMTX

### Windows PowerShell（已下載 mediamtx.exe）

把下載的 `mediamtx.exe` 放進 `streaming` 目錄，另開一個 PowerShell 視窗：

```powershell
Set-Location C:\AIPE_PROJECT\DeepStream_20260805\main_D_20260810\aipe03-3\streaming
.\mediamtx.exe .\mediamtx.yml
```

此視窗要保持開啟。正常時會看到 RTSP `:8554`、WebRTC `:8889` 監聽成功。

若 `mediamtx.exe` 位於其他位置，請把上方執行檔路徑替換成實際位置，但仍要傳入本專案的 `mediamtx.yml`。

### WSL / Bash（建議使用 Docker）

提示字元若是 `aipe@電腦名稱:/mnt/c/...$`，不要使用 `Set-Location` 或 `.\\mediamtx.exe`。在新版根目錄執行：

```bash
cd /mnt/c/AIPE_PROJECT/DeepStream_20260805/main_D_20260810/aipe03-3

docker rm -f nh-mediamtx 2>/dev/null || true

docker run -d \
  --name nh-mediamtx \
  --restart unless-stopped \
  --network aipe03-3_default \
  --add-host=host.docker.internal:host-gateway \
  -p 8554:8554 \
  -p 8889:8889 \
  -p 8189:8189/udp \
  -p 9997:9997 \
  -v "$PWD/streaming/mediamtx.yml:/mediamtx.yml:ro" \
  bluenviron/mediamtx:latest
```

檢查狀態與紀錄：

```bash
docker ps --filter name=nh-mediamtx
docker logs --tail 100 nh-mediamtx
```

這組命令需要第 3 步建立的 `aipe03-3_default` network；如果顯示 network 不存在，先執行 `docker compose up -d --build`。

## 5. 提供四路攝影機串流

DeepStream 預設讀取：

```text
rtsp://host.docker.internal:8554/cam301
rtsp://host.docker.internal:8554/cam302
rtsp://host.docker.internal:8554/cam303
rtsp://host.docker.internal:8554/cam304
```

以上四行是 DeepStream 容器使用的串流網址，不是 Bash 命令，請勿直接貼到終端執行。`host.docker.internal` 是容器連回主機時使用的名稱；WSL 上的 FFmpeg 發布串流時使用 `127.0.0.1`。

現場攝影機或原有推流程式必須把影像發布到這四個路徑。可用 FFmpeg 測試單一路徑：

```powershell
ffmpeg -re -stream_loop -1 -i "C:\影片\test.mp4" -an -c:v libx264 -preset veryfast -tune zerolatency -f rtsp rtsp://127.0.0.1:8554/cam301
```

其餘三路另開視窗，將最後的路徑改成 `cam302`、`cam303`、`cam304`。正式環境請改用實際攝影機來源。

### WSL 使用專案內測試影片發布四路（建議）

```bash
cd /mnt/c/AIPE_PROJECT/DeepStream_20260805/main_D_20260810/aipe03-3
bash scripts/demo_streams.sh start
```

這會把四支測試影片以 640×360/10fps 發布到 `cam301_ai`～`cam304_ai`，供前端與 DeepStream 共用；MediaMTX 重啟時會自動重連。預設對應為：301=`ai/deepstream/input/test.MOV`、302=`../input/test3.MOV`、303=`../input/test5.mp4`、304=`../input/test6.mp4`。系統不強制四路同時存在，只推一路時對應的一格仍可顯示。

確認推流：

```bash
bash scripts/demo_streams.sh status
docker logs --tail 100 nh-mediamtx
```

停止這四個測試推流：

```bash
bash scripts/demo_streams.sh stop
```

## 6. 啟動 Triton

Compose 服務正常後，如果目前在 Windows PowerShell 執行：

```powershell
wsl.exe bash -lc "cd /mnt/c/AIPE_PROJECT/DeepStream_20260805/main_D_20260810/aipe03-3 && bash ai/run_triton.sh"
```

如果提示字元是 `aipe@電腦名稱:/mnt/c/...$`，代表已在 WSL，不要再次呼叫 `wsl.exe`，直接執行：

```bash
cd /mnt/c/AIPE_PROJECT/DeepStream_20260805/main_D_20260810/aipe03-3
bash ai/run_triton.sh
```

檢查 Triton：

```powershell
docker ps --filter name=nh-triton
curl.exe http://127.0.0.1:8010/v2/health/ready
docker logs --tail 100 nh-triton
```

健康檢查應回傳 HTTP 200。

## 7. 啟動四路 DeepStream 骨架偵測

Windows PowerShell：

```powershell
wsl.exe bash -lc "cd /mnt/c/AIPE_PROJECT/DeepStream_20260805/main_D_20260810/aipe03-3 && bash ai/run_deepstream_pose_multi.sh start"
```

已在 WSL/Bash：

```bash
cd /mnt/c/AIPE_PROJECT/DeepStream_20260805/main_D_20260810/aipe03-3
bash ai/run_deepstream_pose_multi.sh start
```

查看狀態與紀錄：

```powershell
wsl.exe bash -lc "cd /mnt/c/AIPE_PROJECT/DeepStream_20260805/main_D_20260810/aipe03-3 && bash ai/run_deepstream_pose_multi.sh status"
wsl.exe bash -lc "cd /mnt/c/AIPE_PROJECT/DeepStream_20260805/main_D_20260810/aipe03-3 && bash ai/run_deepstream_pose_multi.sh logs"
```

紀錄畫面按 `Ctrl+C` 離開，不會停止 DeepStream。

## 8. 開啟與驗證完整版

瀏覽器開啟：

```text
http://localhost/
```

依序確認：

1. 可以登入，首頁四個攝影機有畫面。
2. 切換到 AI/骨架模式後，人物關節與連線顯示在影像上。
3. 發生確認事件時會跳出 `FullScreenAlert` 全螢幕警告。
4. 首頁保留待處理通知，點擊後可重新開啟警告。

跌倒事件由 Detection Bridge 對姿態做連續幀確認：連續 6 幀符合橫躺姿態才建案，同一段持續橫躺只建立一次；人物恢復非跌倒姿態至少 10 幀後才會重新武裝。事件建立後會寫入資料庫並透過 SSE 觸發全螢幕警告。

服務檢查命令：

```powershell
docker compose ps
docker ps --filter name=nh-triton
docker ps --filter name=nh-deepstream-pose-multi
docker compose logs --tail 100 detection-bridge backend
```

連接埠檢查：

```powershell
Get-NetTCPConnection -State Listen |
  Where-Object LocalPort -in 80,8000,8010,8011,8002,8080,8554,8889,9092 |
  Sort-Object LocalPort |
  Select-Object LocalAddress,LocalPort,OwningProcess
```

## 9. 停止完整版

先停 DeepStream 與 Triton：

```powershell
wsl.exe bash -lc "cd /mnt/c/AIPE_PROJECT/DeepStream_20260805/main_D_20260810/aipe03-3 && bash ai/run_deepstream_pose_multi.sh stop"
wsl.exe bash -lc "cd /mnt/c/AIPE_PROJECT/DeepStream_20260805/main_D_20260810/aipe03-3 && bash ai/run_triton.sh stop"
```

再停止 Compose：

```powershell
Set-Location C:\AIPE_PROJECT\DeepStream_20260805\main_D_20260810\aipe03-3
docker compose down
```

最後到 MediaMTX 視窗按 `Ctrl+C`，並停止四個 FFmpeg/攝影機推流視窗。

## 10. 常見問題

### 連接埠已被占用

```powershell
Get-NetTCPConnection -State Listen |
  Where-Object LocalPort -in 80,8000,8010,8011,8002,8080,8554,8889,9092 |
  Select-Object LocalAddress,LocalPort,OwningProcess
```

再用 `Get-Process -Id <OwningProcess>` 找出殘留程式。

### `Docker network not found: aipe03-3_default`

代表尚未執行第 3 步，或不是從本專案根目錄啟動 Compose：

```powershell
Set-Location C:\AIPE_PROJECT\DeepStream_20260805\main_D_20260810\aipe03-3
docker compose up -d --build
```

### 沒有骨架

依序檢查：

```powershell
docker ps --filter name=nh-triton
docker ps --filter name=nh-deepstream-pose-multi
docker compose logs --tail 100 detection-bridge
docker compose logs --tail 100 backend
```

同時確認 `cam301`～`cam304` 確實有影像來源，且前端已切換至 AI/骨架模式。

### 沒有跳警告

全螢幕警告由事件資料觸發，不是只要畫出骨架就會立即跳出。確認後端有收到事件，並檢查：

```powershell
docker compose logs --tail 200 backend
docker compose logs --tail 100 frontend
```

## 整合時未帶入的檔案

為避免洩漏與污染，本整合版沒有複製來源專案的 `.env`、`.venv.broken`、AI 快取、已產生的輸出影片與 `node_modules`。模型、DeepStream 原始碼、設定及必要測試素材均保留。

# Windows／WSL 第二次啟動專案

本文件適用於以下情況：

- `.env` 已設定完成。
- PostgreSQL 已初始化，帳號與資料表已存在。
- Docker 映像與 AI 模型已下載或建置完成。
- 現在只是電腦重開機、Docker Desktop 重啟，或先前手動停止服務後，要再次啟動完整系統。

以下命令都在 **WSL Ubuntu 終端機**執行。提示字元類似：

```text
aipe@WIN-BI3UFR82QS5:/mnt/c/...$
```

不要在 WSL 使用 PowerShell 的 `Set-Location`、`Copy-Item` 或 `notepad`；編輯 Windows 檔案可使用 `notepad.exe .env`。

## 1. 進入新版專案

```bash
cd /mnt/c/AIPE_PROJECT/DeepStream_20260805/main_D_20260810/aipe03-3
```

確認 Docker Desktop 已啟動：

```bash
docker version
```

## 2. 啟動 PostgreSQL

資料庫是本機 Docker 容器 `nh-postgres`，不是 Windows 原生 PostgreSQL 服務。

```bash
docker start nh-postgres
```

確認：

```bash
docker ps --filter name=nh-postgres
```

## 3. 啟動前端、後端、Kafka 與事件橋接

第二次啟動不需要重新建置，使用本機現有映像：

```bash
docker compose up -d --no-build
```

確認：

```bash
docker compose ps
docker logs --tail 30 nh-backend
```

後端日誌應出現：

```text
Application startup complete.
Uvicorn running on http://0.0.0.0:8000
```

若後端顯示 `Restarting` 且日誌出現 PostgreSQL `Connection refused`：

```bash
docker start nh-postgres
docker restart nh-backend
```

> 第二次啟動不要執行 `docker compose up -d --build`。本機 WSL 的 Docker 設定可能使用 `desktop.exe` 憑證助手，重新拉取 `ghcr.io/astral-sh/uv` 時會出現 `error getting credentials`。只有程式碼或 Dockerfile 確實變更時才需要處理憑證問題並重新建置。

## 4. 啟動 MediaMTX

```bash
docker start nh-mediamtx
```

確認：

```bash
docker ps --filter name=nh-mediamtx
docker logs --tail 30 nh-mediamtx
```

## 5. 啟動 Triton

```bash
bash ai/run_triton.sh
```

成功時會顯示 `Triton ready` 與 `yolo_pose_trt 已載入`。也可自行確認：

```bash
curl http://127.0.0.1:8010/v2/health/ready
docker ps --filter name=nh-triton
```

## 6. 啟動四路測試影片

```bash
bash scripts/demo_streams.sh start
```

影片對應：

- 301：`ai/deepstream/input/test.MOV`
- 302：`../input/test3.MOV`
- 303：`../input/test5.mp4`
- 304：`../input/test6.mp4`

確認：

```bash
bash scripts/demo_streams.sh status
```

## 7. 啟動 DeepStream 骨架與跌倒偵測

Triton 和四路影片正常後再執行：

```bash
bash ai/run_deepstream_pose_multi.sh start
```

確認：

```bash
bash ai/run_deepstream_pose_multi.sh status
bash ai/run_deepstream_pose_multi.sh logs
```

按 `Ctrl+C` 只會離開日誌畫面，不會停止容器。

## 8. 完整狀態檢查

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
bash scripts/demo_streams.sh status
```

完整系統至少應包含：

- `nh-postgres`
- `nh-kafka`
- `nh-kafka-ui`
- `nh-backend`
- `nh-frontend`
- `nh-detection-bridge`
- `nh-mediamtx`
- `nh-triton`
- `nh-deepstream-pose-multi`
- 四路 FFmpeg 推流程序

網址：

- 前端：<http://localhost>
- 後端 API 文件：<http://localhost:8000/docs>
- Kafka UI：<http://localhost:8080>
- Triton 健康檢查：<http://localhost:8010/v2/health/ready>

## 9. 暫停或完整停止

只停止新案件寫入資料庫，保留網站與資料庫：

```bash
docker stop nh-detection-bridge
```

停止影片與 AI 運算，但保留前後端及資料庫：

```bash
bash scripts/demo_streams.sh stop
bash ai/run_deepstream_pose_multi.sh stop
bash ai/run_triton.sh stop
docker stop nh-mediamtx
```

完整停止：

```bash
bash scripts/demo_streams.sh stop
bash ai/run_deepstream_pose_multi.sh stop
bash ai/run_triton.sh stop
docker stop nh-mediamtx
docker compose stop
docker stop nh-postgres
```

這些停止命令不會刪除 PostgreSQL 資料。不要執行 `docker compose down -v`，`-v` 可能刪除資料庫 Volume。

## 10. 最短版啟動順序

環境完全設定過後，每次開機只需：

```bash
cd /mnt/c/AIPE_PROJECT/DeepStream_20260805/main_D_20260810/aipe03-3
docker start nh-postgres
docker compose up -d --no-build
docker start nh-mediamtx
bash ai/run_triton.sh
bash scripts/demo_streams.sh start
bash ai/run_deepstream_pose_multi.sh start
docker compose ps
```

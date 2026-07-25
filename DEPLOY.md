# 部署與啟動（docker-compose）

一鍵把通報層四個容器（Kafka / kafka-ui / 後端 / 前端）跑起來。

## 前置需求

- Docker Desktop（執行中）
- 一份 `.env` 放在專案根目錄（含 DB 帳密、SECRET_KEY、EVENT_API_KEY、S3 金鑰）
  —— 不進 git，需向專案負責人私下取得

## 啟動

```bash
docker compose up -d --build
```

| 服務 | 網址 | 說明 |
| --- | --- | --- |
| 前端 | http://localhost | React 畫面（nginx 服務 + `/api` 反向代理到後端） |
| 後端 | http://localhost:8000 | FastAPI（同一容器內 uvicorn + kafka consumer 併跑） |
| Kafka | localhost:9092 | KRaft 模式，無 Zookeeper |
| kafka-ui | http://localhost:8080 | 監控 topic 與訊息 |

停止：`docker compose down`

## AI（判斷層）

不在這包。跑在能跑 AI 的機器上，當 producer 打 `localhost:9092`、topic `processed-reports`。

## 常見問題

- **`apache/kafka:3.9.0` 下載一直 `EOF`**：WSL2 MTU 問題。`~/.docker/daemon.json` 加
  `"mtu": 1280` 與 `"max-download-attempts": 20`，重啟 Docker Desktop 後再 `docker compose up -d --build`。
- **後端 `Exited`、log 說資料庫連不上**：檢查 `.env` 的 DB 帳密是否正確。
- **改了程式或 compose 後**：`docker compose up -d --build` 會重建受影響的容器。

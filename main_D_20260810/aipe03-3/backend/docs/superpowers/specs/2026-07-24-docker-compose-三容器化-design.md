# 通報層容器化部署設計（docker-compose）

2026-07-24 定案。將 fulilian 通報層打包成一鍵可啟動的容器環境，供「跑得動 AI 的隊友」在自己本機執行。核心三容器（kafka / backend / frontend）＋除錯用 kafka-ui，共四容器。

## 目標與階段

三階段目標，本設計只做第一與第二階段：

1. 本機能同時跑起前後端
2. 整包可攜：隊友 `docker compose up` 即可跑（本設計範圍）
3. 確認可攜後上雲端（本設計不含，但架構須不阻礙）

## 範圍

- 一份 `docker-compose.yml` 拉起四個容器：Kafka、kafka-ui、backend、frontend
- Kafka 由 Zookeeper 版改為 KRaft 版（拿掉 Zookeeper）
- 新寫 `backend/Dockerfile`；`frontend/Dockerfile` 沿用，`frontend/nginx.conf` 加反向代理
- AI（albert）不在本包，跑在隊友本機、當 Kafka producer

非目標：資料庫容器化（繼續連 AWS RDS）、上雲、CI/CD。

## 三容器

### 1. kafka

- `image: apache/kafka`（官方 KRaft，免 Zookeeper）
- 對外埠 `9092`，對外公告 `localhost:9092`、對內公告 `kafka:29092`（維持現值不變）
- 因對外/對內位址不變，albert 的 producer（連 `localhost:9092`）與 backend consumer（連 `kafka:29092`）皆零改碼

### 1b. kafka-ui（除錯用）

- `image: provectuslabs/kafka-ui`（現成 image，免 Dockerfile）
- 對外埠 `8080`，內線連 `kafka:29092`
- 純除錯／監控：用瀏覽器看 topic 與訊息，快速判斷「事件沒進前端」是 AI 沒送進 Kafka、還是 backend 沒收到
- 非系統運作必要，可隨時移除

### 2. backend

- `build: ./backend`（需新寫 `backend/Dockerfile`）
- **一個容器內同時跑兩支程式**（合併方案 B）：以啟動腳本先背景啟動 `python -m kafka_consumer`，再前景啟動 `uvicorn main:app`（`pyproject.toml`/`uv.lock` 已於本次重構搬入 `backend/`，故 build context 為 `./backend`）
- 對外埠 `8000`
- `KAFKA_BOOTSTRAP_SERVERS=kafka:29092`（走內線）
- 資料庫連 AWS RDS（`DB_HOST` 等由 `.env` 帶入，不變）
- `depends_on: kafka`

### 3. frontend

- `build: ./frontend`（沿用現有多階段 Dockerfile：node 編譯 → nginx 服務）
- 對外埠 `80`
- nginx 身兼兩職：①服務 React 靜態網頁 ②反向代理，把 `/events`、`/stream`、`/login` 等後端請求轉發 `backend:8000`
- 前端 API base 改為同源（不再走 build 時烤死的 ngrok 位址），瀏覽器只與 frontend 對話
- `depends_on: backend`

## 網路與埠

- compose 內建網路：容器間以 service 名互連（`kafka`、`backend`、`frontend`）
- 埠對應（host:container）：`9092:9092`、`8080:8080`（kafka-ui）、`8000:8000`、`80:80`
- 內線 vs 外線：容器內用 service 名（`kafka:29092`、`backend:8000`）；host 與 AI 用 `localhost:9092`

## 資料流

```
AI(隊友本機, localhost:9092) → kafka → consumer(backend容器內) → POST /events(自家網站)
  → SSE → nginx(frontend, /stream 轉發) → 瀏覽器
```

## 需改動 / 新增的檔案

| 檔案 | 動作 |
| --- | --- |
| `docker-compose.yml` | 重寫：三 service，Kafka 改 KRaft |
| `backend/Dockerfile` | 新增 |
| `backend/`（啟動腳本） | 新增：背景跑 consumer + 前景跑 uvicorn |
| `frontend/nginx.conf` | 加反向代理規則；`/stream`（SSE）關閉緩衝 |
| `frontend/src/api/client.ts` | API base 改同源（配合 nginx 代理） |

## SSE 注意

`/stream` 是長連線推播。nginx 代理該路徑須關閉回應緩衝（如 `proxy_buffering off`），否則推播會被 nginx 卡住不即時。

## .env 交付

`.env`（RDS 帳密、SECRET_KEY、EVENT_API_KEY、S3 金鑰）不進 git。隊友須另外私下取得一份 `.env` 才能 `docker compose up`。實作時定「怎麼給」。

## 已知取捨

- 合併方案 B：consumer 與網站同容器，consumer 若默默掛掉網站不會察覺（demo 可接受；正規做法是拆兩容器）。
- 繼續共用 RDS：隊友需 RDS 帳密與連得到 AWS，非完全「自帶電池」（因對象為團隊隊友，可接受）。

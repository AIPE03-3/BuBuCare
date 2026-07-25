# 部署與啟動（docker-compose）

一鍵把通報層四個容器（Kafka / kafka-ui / 後端 / 前端）跑起來。

## 前置需求

- Docker Desktop（執行中）
- **`.env` 放進專案根目錄**：含 DB 帳密、SECRET_KEY、EVENT_API_KEY、S3 金鑰。
  不進 git，需向專案負責人私下取得，欄位對照 `.env.example`。

沒放就執行 `docker compose up` 的話，會直接被擋下來並看到：

```
error while interpolating services.backend.labels.env_check:
required variable DB_PORT is missing a value: 找不到專案根目錄的 .env，請先放好再執行 docker compose up
```

這是刻意設計的，看到它就是「先去把 `.env` 放好」，不用查別的。

## 啟動

```bash
docker compose up -d --build
```

第一次會花幾分鐘（下載 image、裝套件、build 前端）。之後再啟動就很快。

| 服務 | 網址 | 說明 |
| --- | --- | --- |
| 前端 | http://localhost | React 畫面（nginx 服務 + `/api` 反向代理到後端） |
| 後端 | http://localhost:8000 | FastAPI（同一容器內 uvicorn + kafka consumer 併跑） |
| Kafka | localhost:9092 | KRaft 模式，無 Zookeeper |
| kafka-ui | http://localhost:8080 | 監控 topic 與訊息 |

### 登入帳號

| 員編 | 密碼 | 角色 |
| --- | --- | --- |
| A001 | 123456 | admin |
| E001 | 123456 | staff（陳雅文） |

`.env` 指向的是共用的 AWS RDS，已經初始化過，**不需要另外建表或種資料**。
（只有換成一個全新的空資料庫時才要做一次：
`docker compose exec backend uv run --no-sync python -m init_db`，
會建表 + 補欄位 + 種示範資料 + 建上面兩個帳號，可重複執行不會報錯。）

### 停止

```bash
docker compose stop   # 只停，容器保留，下次 start 很快
docker compose down   # 停並移除容器
```

`down` 會一併清掉 Kafka 的 topic 與 consumer 讀取進度（Kafka 沒掛 volume）。
事件資料存在 AWS RDS，不受影響。

## AI（判斷層）

不在這包。當 producer 打 topic `processed-reports`。

**目前只支援 AI 跟這包跑在同一台電腦上**，位址填 `localhost:9092`。
原因：`docker-compose.yml` 裡 Kafka 對外宣告的位址寫死是 `PLAINTEXT://localhost:9092`，
別台電腦連進來時，Kafka 會回他「請連 localhost:9092」，他就會轉去連自己的機器而失敗。
真要跨機，得把該行的 `localhost` 改成這台主機的區網 IP。

## 常見問題

- **四個容器都顯示 `Up`，但事件收不到**：先確認 consumer 活著——
  `docker compose logs backend | Select-String consumer`（PowerShell）。
  正常會看到「consumer 啟動，監聽 topic=processed-reports」。
  若一直印「consumer 結束……5 秒後重啟」，代表連不到 Kafka，
  用 `docker compose ps` 看 kafka 是不是 healthy。

- **後端一直重開，log 說「找不到 /app/.env」**：根目錄的 `.env` 曾被 Docker 建成資料夾
  （舊版才會發生）。`docker compose down`、把那個 `.env` 資料夾刪掉、放進真的 `.env` 檔，再 up。

- **後端 `Exited`、log 說資料庫連不上**：檢查 `.env` 的 DB 帳密是否正確。

- **`Ports are not available` / 網址打不開（埠號被佔）**：Windows 上 80 埠常被 IIS 之類佔用。
  改 `docker-compose.yml` 裡對應服務埠號**左邊**那個數字即可（例如前端改成 `"8081:80"`，
  之後用 http://localhost:8081 開）。前端打 API 走同源相對路徑 `/api`，改埠號不必重 build。

- **`apache/kafka:3.9.0` 下載一直 `EOF`**：WSL2 MTU 問題。`~/.docker/daemon.json` 加
  `"mtu": 1280` 與 `"max-download-attempts": 20`，重啟 Docker Desktop 後再 `docker compose up -d --build`。

- **改了程式或 compose 後**：`docker compose up -d --build` 會重建受影響的容器。

## 這包刻意加的防呆，改動時別順手拿掉

| 設定 | 在哪 | 拿掉會怎樣 |
| --- | --- | --- |
| `labels: env_check: ${DB_PORT:?...}` | `docker-compose.yml` | 沒放 `.env` 就 up 時，Docker 會在根目錄建一個 `.env` 資料夾，之後真的 `.env` 檔放不進去 |
| Kafka `healthcheck` + 後端 `condition: service_healthy` | `docker-compose.yml` | 冷啟動時 consumer 會在 Kafka 開好之前就 `NoBrokersAvailable` 收工 |
| `start.sh` 裡 consumer 的 `while` 重啟迴圈 | `backend/start.sh` | consumer 死掉不會自己回來，容器卻仍顯示 `Up`（最難查的那種故障） |
| `uv run --no-sync` | `backend/start.sh` | 每次啟動都連 PyPI 重裝套件（含測試用套件），沒網路就起不來 |
| `TZ: Asia/Taipei` | `docker-compose.yml` | 容器預設 UTC，寫進 DB 的時間會少 8 小時 |
| `exec uv run ... uvicorn` | `backend/start.sh` | 停止訊號傳不到 uvicorn，每次關閉都要空等 10 秒 |

`.env` 一律用**掛檔案**（volume）送進容器，不要改成 `env_file`：
實測 `env_file` 會把密碼裡的 `$` 當成變數展開挖空（`p@ss$word9$$x` → `p@ss$x`），
加上 `format: raw` 雖然不挖空，卻會把值兩側的引號一起當成密碼內容。

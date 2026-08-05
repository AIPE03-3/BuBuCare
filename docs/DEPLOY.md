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

| 服務     | 網址                  | 說明                                                |
| -------- | --------------------- | --------------------------------------------------- |
| 前端     | http://localhost      | React 畫面（nginx 服務 +`/api` 反向代理到後端）   |
| 後端     | http://localhost:8000 | FastAPI（同一容器內 uvicorn + kafka consumer 併跑） |
| Kafka    | localhost:9092        | KRaft 模式，無 Zookeeper                            |
| kafka-ui | http://localhost:8080 | 監控 topic 與訊息                                   |

### 登入帳號

| 員編 | 密碼   | 角色            |
| ---- | ------ | --------------- |
| A001 | 123456 | admin           |
| E001 | 123456 | staff（陳雅文） |

`.env` 指向的是共用的 AWS RDS，已經初始化過，**不需要另外建表或種資料**。
（只有換成一個全新的空資料庫時才要做一次：
`docker compose exec backend uv run --no-sync python -m init_db`，
會建表 + 種示範資料 + 建上面兩個帳號，可重複執行不會報錯。
註：它只建「不存在的表」，**不會**為既有表補欄位——改欄位要手動 `ALTER TABLE` 或先 `DROP TABLE` 再跑。）

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

| 設定                                                       | 在哪                   | 拿掉會怎樣                                                                                   |
| ---------------------------------------------------------- | ---------------------- | -------------------------------------------------------------------------------------------- |
| `labels: env_check: ${DB_PORT:?...}`                     | `docker-compose.yml` | 沒放`.env` 就 up 時，Docker 會在根目錄建一個 `.env` 資料夾，之後真的 `.env` 檔放不進去 |
| Kafka`healthcheck` + 後端 `condition: service_healthy` | `docker-compose.yml` | 冷啟動時 consumer 會在 Kafka 開好之前就`NoBrokersAvailable` 收工                           |
| `start.sh` 裡 consumer 的 `while` 重啟迴圈             | `backend/start.sh`   | consumer 死掉不會自己回來，容器卻仍顯示`Up`（最難查的那種故障）                            |
| `uv run --no-sync`                                       | `backend/start.sh`   | 每次啟動都連 PyPI 重裝套件（含測試用套件），沒網路就起不來                                   |
| `TZ: Asia/Taipei`                                        | `docker-compose.yml` | 容器預設 UTC，寫進 DB 的時間會少 8 小時                                                      |
| `exec uv run ... uvicorn`                                | `backend/start.sh`   | 停止訊號傳不到 uvicorn，每次關閉都要空等 10 秒                                               |

`.env` 一律用**掛檔案**（volume）送進容器，不要改成 `env_file`：
實測 `env_file` 會把密碼裡的 `$` 當成變數展開挖空（`p@ss$word9$$x` → `p@ss$x`），
加上 `format: raw` 雖然不挖空，卻會把值兩側的引號一起當成密碼內容。

## 機器層監控（Netdata，原生安裝）

2026-08-05 補上的機器層監控。**這是原生安裝（systemd 服務），不在任何 docker-compose 裡、
不進版控**——換一台機器要重裝一次，別的開發機 `git clone` 後跑 `docker compose up`
不會自動有監控。這份文件是唯一的紀錄，收斂進主 `docker-compose.yml` 時要靠它。

### 裝了什麼

- **Netdata 版本**：`v2.10.4`（stable channel；一開始誤用 `--nightly-channel` 裝過
  `v2.10.0-1001-nightly`，後來整個解除安裝重裝成 stable，見下方「踩過的坑」）
- **安裝方式**：官方 kickstart 腳本，原生二進位套件（不是 Docker 容器）：
  ```bash
  wget -O /tmp/netdata-kickstart.sh https://get.netdata.cloud/kickstart.sh
  sh /tmp/netdata-kickstart.sh --stable-channel \
    --claim-token <claim token，機密，問專案負責人要> \
    --claim-rooms <room ID> \
    --claim-url https://app.netdata.cloud
  ```
  `--claim-token` 是機密，**絕對不要寫進任何會進版控的檔案**（包含這份文件），
  只能私下取得、貼在自己終端機執行，不要留存。
- **服務管理**：systemd，`systemctl status netdata` / `systemctl restart netdata`
- 本地儀表板：http://127.0.0.1:19999 （免登入，跟雲端是分開的兩條路徑）
- 雲端：https://app.netdata.cloud，機器在 Rooms 底下顯示為 `Rap-PC`

### 改了哪些設定

原生安裝預設不包含以下兩項，是本輪額外開的，設定檔都在 `/etc/netdata/`（**不進版控**，
系統套件本體在 `/usr/lib/netdata/` 那份是唯讀範本，永遠複製一份到 `/etc/netdata/` 再改，
不要直接改 `/usr/lib/netdata/` 底下的檔案，套件更新會被覆蓋）：

1. **GPU 監控**（NVIDIA RTX 5060 Ti）——`nvidia_smi` collector。
   本機是 WSL2，`nvidia-smi` 的路徑是 `/usr/lib/wsl/lib/nvidia-smi`，
   不在 netdata 服務行程的預設 PATH 上，需要用 `binary_path` 明講：
   ```bash
   mkdir -p /etc/netdata/go.d
   cat > /etc/netdata/go.d/nvidia_smi.conf << 'EOF'
   jobs:
     - name: nvidia_smi
       binary_path: /usr/lib/wsl/lib/nvidia-smi
   EOF
   systemctl restart netdata
   ```
   （若不是 WSL2 而是原生 Linux，`nvidia-smi` 通常就在標準 PATH 上，可能不需要這段。）

2. **Triton 推論指標**——用 Netdata 內建的 `prometheus`（通用 Prometheus 端點抓取器），
   指向 Triton 自帶的 metrics 端點：
   ```bash
   mkdir -p /etc/netdata/go.d
   cat > /etc/netdata/go.d/prometheus.conf << 'EOF'
   jobs:
     - name: triton
       url: 'http://127.0.0.1:8002/metrics'
   EOF
   systemctl restart netdata
   ```
   接進來的圖表以 `prometheus_triton.*` 為前綴，含每顆模型（`yolo_pose` / `rt_detr` /
   `action_transformer`）分開的推論次數（`nv_inference_count`）、佇列延遲
   （`nv_inference_queue_duration_us`）、GPU/CPU 計算延遲
   （`nv_inference_compute_infer_duration_us` 等）。

### 接了哪些端點

| 端點 | 誰在跑 | Netdata 怎麼接 | 圖表前綴 |
|---|---|---|---|
| `http://127.0.0.1:8002/metrics` | Triton（自帶，`ai/run_triton.sh` 啟動時就有） | `prometheus` collector（見上） | `prometheus_triton.*` |
| Docker 容器（13 個） | `docker-compose.yml` 起的所有服務 | 內建 `cgroups`/`docker` collector，零設定自動偵測，抓 cgroup 的 CPU/記憶體/IO | `cgroup_<容器名>.*`、`docker_local.*` |
| 主機層（CPU/記憶體/磁碟/網路） | 系統本身 | 內建，零設定 | `system.*`、`disk.*`、`net.*` |
| GPU | RTX 5060 Ti | `nvidia_smi` collector（見上） | `nvidia_smi.*` |

**本輪刻意不接**（使用者已指示，理由見 `docs/NEXT_STAGE.md` 第 4 項）：
backend 的 `/metrics`（該端點本身也還是 404，`backend/observability/` 沒動）、
`gcp_vm_environment/` 那套 Prometheus + Grafana + JMX exporter、
Kafka 監控（JMX exporter 沒裝，broker 本身也還沒有 metrics 端點）。

### 解除安裝

原生安裝的官方解除安裝方式，一樣用 kickstart 腳本加旗標（需要 sudo）：

```bash
sh /tmp/netdata-kickstart.sh --uninstall --yes
```

⚠️ **踩過的坑**：解除安裝後 `systemctl status netdata` 可能同時顯示 `masked` 又
`active (running)`——這是正常會發生的中間狀態，代表 systemd 的服務定義已經被拔掉
（symlink 到 `/dev/null`），但**在那之前就已經啟動的舊行程不會被自動殺掉**。
乾淨收尾要多做：

```bash
sudo systemctl unmask netdata     # 解除 mask，避免殘留設定卡住下次安裝
sudo systemctl stop netdata
sudo pkill -9 -f /usr/sbin/netdata
pgrep -af netdata                 # 應該完全沒有輸出（沒有殘留行程）才算乾淨
```

確認沒有殘留行程後才重新執行 kickstart 安裝指令，不然舊的 claim 狀態可能不會正確
切換到新的 room（實測：`--claim-rooms` 換了新值，但沒清乾淨殘留行程時，
`claimed-id` 不會變、雲端網頁也看不到節點——直到卸載乾淨重裝才解決）。

### 已知限制 / 尚未收斂

- 這套是**手動裝在這台機器上**，其他開發機（另一台 5060 Ti、Mac）都還沒裝，
  也没有寫成腳本自動化——目前是照這份文件的指令手動照抄。
- 尚未收斂進主 `docker-compose.yml`。要收斂時的三件事（見 `docs/NEXT_STAGE.md`
  「決策 1」）：①在 `docker-compose.yml` 加 netdata 服務（容器化版本）
  ②把上面那些 `/etc/netdata/go.d/*.conf` 改寫成 repo 裡的檔案，容器啟動時掛進去
  ③把這台機器現在跑的原生版解除安裝（兩份 netdata 同機會重複回報，claim 也會衝突）。
- Kafka、backend `/metrics` 都還沒接，本輪範圍不含這兩項。

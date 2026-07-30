# 在 macOS（Apple Silicon）上把系統跑起來

**這份是操作手冊**：開機後照著跑就有東西看。
想知道「為什麼這樣設定、還有什麼沒做完、踩過哪些坑」看 [`MAC_SETUP_WBS.md`](docs/MAC_SETUP_WBS.md)。

**不確定現在做到哪、什麼服務活著** —— 不要猜，跑自檢：

```bash
bash scripts/check_mac_env.sh
```

每一行對應 WBS 的一個 T 編號，看到第一個 ❌ 就從那項接手。

---

## 一、一次性設定（每台機器做一次）

| 項目 | 指令 |
|---|---|
| 護欄 hooks | `git config core.hooksPath .githooks` |
| 兩個 venv | 根 `.venv`（後端／VLM）與 `ai/.venv`（推論／訓練），**不要合併** |
| Triton CPU repo | `./ai/make_cpu_repo.sh` |
| MediaMTX 設定 | `cp streaming/mediamtx.yml.example streaming/mediamtx.yml` 後改 4 處（見 WBS T4-1）|
| ClearML 憑證 | `cp ai/clearml.conf.example ~/clearml.conf`，填 credentials（`chmod 600`）|
| `.env` | Triton URL、`MEDIAMTX_BASE_URL`、`DETECT_STREAM_FFMPEG`、`S3_RW_*`、`LABEL_STUDIO_*` |

> **這台沒有 Homebrew**。ffmpeg 走 `imageio-ffmpeg` 附的靜態版（`.env` 指路），
> mediamtx 走 docker image。兩者都不在 `PATH` 上，自檢腳本三種來源都認。

---

## 二、每次開機的啟動順序

### P1 核心鏈（跌倒偵測必需）

```bash
# 1) Docker Desktop
open -a Docker

# 2) Triton（CPU / 全 ONNX）
#    ⚠️ 這支是 --rm 容器，關機或 docker stop 後不會自己回來，每次都要重跑
TRITON_GPUS=none HTTP_PORT=8010 GRPC_PORT=8011 METRICS_PORT=8002 \
  MODEL_REPO="$(pwd)/ai/triton_repo_cpu" \
  LOAD_MODELS="yolo_pose rt_detr_onnx action_transformer" ./ai/run_triton.sh

# 3) Kafka / backend / frontend / kafka-ui
docker compose up -d
```

### P4 串流（要看即時畫面才需要）

```bash
# MediaMTX 有 restart:unless-stopped，Docker 起來後它自己會回來；沒有才跑這行
docker run -d --name nh-mediamtx --restart unless-stopped \
  -v "$(pwd)/streaming/mediamtx.yml:/mediamtx.yml:ro" \
  -p 8554:8554 -p 8889:8889 -p 9997:9997 -p 8189:8189/udp \
  bluenviron/mediamtx:latest

# 推 mp4 當 cam_in（沒有實體攝影機時的畫面來源）
FF=$(grep '^DETECT_STREAM_FFMPEG=' .env | cut -d= -f2-)
"$FF" -re -stream_loop -1 -i ai/test_demo/test6.mp4 \
  -an -c:v copy -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam_in
```

### P5 MLOps（只有跑重訓迴路才需要，很吃資源）

```bash
docker compose -p ai -f ai/docker-compose-clearml.yml \
                     -f ai/docker-compose-clearml.mac.yml up -d
docker compose -p ai -f ai/docker-compose-labelstudio.yml up -d

# 重訓執行者（host 原生跑，不帶 --gpus）
CLEARML_AGENT_SKIP_PIP_VENV_INSTALL="$(pwd)/ai/.venv/bin/python" \
CLEARML_AGENT_SKIP_PYTHON_ENV_INSTALL=1 \
  ai/.venv/bin/clearml-agent daemon --queue default --foreground
```

> `-p ai` 不能省 —— volume 名靠它對上既有的 `ai_clearml-*` / `ai_lsdata`。

---

## 三、跑一次完整的跌倒偵測

**順序不能反**：VLM worker 是 `auto_offset_reset='latest'`，先跑推論它會看不到事件。

```bash
# 終端 A：VLM 二審（根 .venv，必須 cd ai —— 它 import 同目錄的兄弟模組）
cd ai && VLM_MODEL_NAME=qwen2.5vl:7b ../.venv/bin/python -u vlm_worker.py

# 終端 B：推論（ai/.venv）
HEADLESS=1 SINGLE_SOURCE=ai/test_demo/test6.mp4 DETR_EVERY_N=5 \
  ai/.venv/bin/python -u ai/inference_test.py
```

**要同時推偵測畫面到前端**（`cam_out`）就**不能用 `SINGLE_SOURCE`**，改讓它走預設的
`CAMERA_SOURCE=backend` 從 `cam_in` 拉流：

```bash
HEADLESS=1 DETECT_STREAM=1 ai/.venv/bin/python -u ai/inference_test.py
```

> `-u` 不要省：stdout 在非終端機時是整塊緩衝，沒有它會讓你以為程式卡住了。

---

## 四、網址與埠

| 服務 | 網址 | 備註 |
|---|---|---|
| 前端 | <http://127.0.0.1> | 事件中心 `/events`、監控 `/monitoring` |
| 後端 API | <http://127.0.0.1:8000/docs> | |
| Triton | <http://127.0.0.1:8010> | **8010 不是 8000**（8000 被 backend 佔）|
| Kafka UI | <http://127.0.0.1:8080> | |
| MediaMTX API | <http://127.0.0.1:9997/v3/paths/list> | 看頻道有沒有畫面（認 `ready`，不要看 WHEP 狀態碼）|
| Label Studio | <http://127.0.0.1:8082> | 未登入回 302 是正常的 |
| ClearML | <http://127.0.0.1:8085> | API 8008、fileserver 8081 |
| Ollama | <http://127.0.0.1:11434> | `qwen2.5vl:7b` |

---

## 五、症狀 → 解法（都是實際踩過的）

| 症狀 | 原因與解法 |
|---|---|
| `nh-triton` 不見了 | `--rm` 容器，`docker stop` 等於刪掉。重跑第二節的 `run_triton.sh` |
| Triton 三顆全 UNAVAILABLE | 用到 `ai/triton_repo/`（寫死 `KIND_GPU`）。要用 `ai/triton_repo_cpu/`，重跑 `./ai/make_cpu_repo.sh` |
| 前端監控頁一直轉圈 | 換過 Wi-Fi。區網 IP 變了要**同時**改 `streaming/mediamtx.yml` 的 `webrtcAdditionalHosts` 與 `.env` 的 `MEDIAMTX_BASE_URL`（`ipconfig getifaddr en0`）|
| 設了 `DETECT_STREAM=1` 但 `cam_out` 沒畫面 | 同時設了 `SINGLE_SOURCE`。兩者互斥且**靜默失敗**，見第三節 |
| VLM 二審沒反應 | 先起 worker 再跑推論。已經積壓的用 `kafka-consumer-groups.sh --describe --group vlm-brain-cluster` 查，要丟掉加 `--reset-offsets --to-latest --execute` |
| 前端影片點不開 | `clip_path` 不是 `s3://` 開頭。`.env` 要有 `CLIP_S3_BUCKET`，否則存的是本地路徑 |
| clearml-agent 秒掛 `No module named pip` | `ai/.venv` 是 uv 建的沒有 pip。加 `CLEARML_AGENT_SKIP_PYTHON_ENV_INSTALL=1`，**不要**去補裝 pip（它接著會重裝幾百 MB 相依）|
| Triton 新版本 UNAVAILABLE，說少 `model.onnx.data` | torch 2.13 匯出的是外部權重檔。用 `onnx.save(..., save_as_external_data=False)` 併成單一檔 |
| 熱載回 `failed to poll from model repository`，但三顆 `/ready` 都還是 200 | **Triton 跑著的時候跑了 `make_cpu_repo.sh`**。它會 `rm -rf` 重建目錄，容器的 bind mount 指向被刪掉的舊 inode → 容器內 `/models` 變成空的（`docker exec nh-triton ls /models` 一看就知道）。已載入記憶體的模型照樣服務，所以 `/ready` 還是 200，**只有 reload 會失敗** —— 症狀很誤導。**解法：重跑 `run_triton.sh`**；要重建 repo 就先停 Triton |
| 推論說連不上後端 | `.env` 要有 `BACKEND_API_USER` / `BACKEND_API_PASSWORD`（推論靠它拿裝置清單）|

### ⚠️ 兩件會弄壞另一台的事

1. **不要在版控的 `config.pbtxt` 加 `version_policy` 鎖新版本。**
   權重（`ai/triton_repo/*/[0-9]*/`）不進版控，對方 pull 到「鎖 v2 的設定」卻只有 `1/`
   → explicit 模式一顆倒全倒，**整台 Triton 起不來**。版本鎖只改 `triton_repo_cpu/`。

2. **`prepare_dataset.py` 會覆蓋 `ai/dataset_splits/`**（那是進版控的量測證據）。
   訓練實際讀的是 `detection_dataset/train.txt`，所以跑完 `git checkout ai/dataset_splits/` 還原。

---

## 六、關閉

```bash
./ai/run_triton.sh stop          # Triton
docker compose down              # kafka / backend / frontend / kafka-ui
docker stop nh-mediamtx          # 串流

# MLOps（資料留著，volume 不刪）
docker compose -p ai -f ai/docker-compose-clearml.yml \
                     -f ai/docker-compose-clearml.mac.yml stop
docker compose -p ai -f ai/docker-compose-labelstudio.yml stop
```

> **不要用 `docker system prune -a`** —— Triton image 有 20.4GB，清掉要重抓很久。

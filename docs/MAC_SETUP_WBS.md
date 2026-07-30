# 在 macOS (Apple Silicon) 上跑起整套系統 —— WBS

**目標**：這台 M2 Pro 上跑通完整鏈路 —— 影像辨識 → Kafka → 後端 → 前端、VLM 二審、MLOps 重訓迴路。

**分支**：`feat/mac-local-runbook`（從 `test/main-integration` 開）

---

## 〇、中斷之後怎麼銜接（每次開工先做這件事）

**不要靠記憶判斷做到哪裡，跑自檢**：

```bash
bash scripts/check_mac_env.sh      # 見 T0-6；還沒建立前用下面第三節的逐項指令
```

然後看第四節 WBS 表的狀態欄，找第一個 `☐` 開始做。每完成一項：

1. 把該列狀態改成 `☑`
2. 在第五節「執行紀錄」追加一行（日期 + 做了什麼 + 實際數字/錯誤）
3. 該項若推翻了第六節的假設，**去改第六節**，不要只寫在紀錄裡

---

## 一、已定案的決策（不要重新討論）

| # | 決策 | 理由 |
|---|---|---|
| D1 | Triton 走 **CPU 模式 + 全 ONNX**，`TRITON_GPUS=none` | 這台無 NVIDIA GPU。`albert_chiang` 分支在 M 系列上就是這樣跑通的（三顆全 `onnxruntime_onnx` + `KIND_CPU`）|
| D2 | `rt_detr` 改打 **`rt_detr_onnx`**，用 `.env` 的 `TRITON_DETR_URL` 繞過，**不改 `config.pbtxt`** | `rt_detr` 是 `tensorrt_plan`，Mac 編不出引擎。改版控檔會弄壞 5060 Ti 那台 |
| D3 | Triton HTTP 走 **8010**、gRPC 8011 | 8000 被 backend 佔（`CLAUDE.md` 第四節）|
| D4 | PostgreSQL **用雲端 AWS RDS**，不起本機 DB | `.env` 既有設定，已實測 5432 可連 |
| D5 | VLM 用 **`qwen2.5vl:7b`**（本機已有），不用 `llava:latest` | `vlm_client.py:21` 預設是 llava，本機沒裝。albert 也是用 qwen2.5vl |
| D6 | `vlm_worker.py` 跑在**根 `.venv`**；`inference_test.py` 跑在 **`ai/.venv`** | 前者只要 kafka+langgraph，後者要 torch/ultralytics/cv2。兩個 venv 各有各的用途，不要合併 |
| D7 | MLOps 的 ClearML **自架 + Rosetta 模擬**，用 override 檔隔離 Mac 專屬設定 | `clearml/server` 只有 amd64 image。albert 在 M 系列上就是這樣跑的 |
| D8 | 重訓走 `TRAIN_DEVICE=cpu`、少量 epoch，**只驗流程不追精度** | albert 的 pipeline 就是 `device='cpu'` + `epochs=1`。RT-DETR 在 MPS 上能否訓練**未經驗證** |
| D9 | S3 事件影片用組員的 **`S3_RW_*` 讀寫金鑰** | 後端只認 `s3://` 路徑才簽得出可播網址；唯讀金鑰上傳會 403 |

---

## 二、已查證的環境事實（省得重查）

| 項目 | 事實 | 查證方式 |
|---|---|---|
| CPU | Apple M2 Pro / arm64 | `uname -m` |
| `tritonserver:25.10-py3` | **有 linux/arm64 manifest** → 原生可跑 | nvcr.io registry API |
| `clearml/server:latest` | **只有 linux/amd64** → 必須模擬 | Docker Hub registry API |
| `label-studio` / `mediamtx` / `kafka` / `kafka-ui` / `mongo` / `redis` | 都有 arm64 | 同上 |
| `elasticsearch:7.17.9`（docker.elastic.co） | **架構未確認**（該 registry 查 manifest 需認證）。失敗時照 albert 改用 Docker Hub `elasticsearch:8.19.9`（有 arm64）| — |
| RDS 5432 | 可連 | `nc -zv` |
| Ollama | 服務在跑，有 `qwen2.5vl:7b` / `qwen2.5:7b`，**沒有 llava** | `ollama list` |
| `ai/.venv` | 有 torch 2.13 / ultralytics 8.4.108 / cv2 / onnxruntime；**缺 kafka、dotenv、boto3、av、tritonclient、clearml** | `site-packages` 清單 |
| 根 `.venv` | 有 fastapi / sqlalchemy / kafka / langchain / langgraph / langchain_ollama；**缺 ollama 套件** | 同上 |
| `ffmpeg` / `mediamtx` | **都不在 PATH 上，但都已備妥**：ffmpeg = `imageio-ffmpeg` 附的 7.1 arm64 靜態版（`.env` 指路）、mediamtx = docker image（見 T4-0）| `check_mac_env.sh` |
| 模型來源權重 | `yolo11s-pose.pt` ✅ `action_transformer.pth` ✅ `rtdetr-l.pt` ❌（ultralytics 會自動下載）| `ls ai/` |
| `albert_chiang` 分支 | 舊架構 `Fall/`，**零模型權重**，MLOps 腳本已於 PR #22 全部搬進 `ai/`。剩餘參考價值：`requirements.txt`、`start_*.sh`、`mediamtx(example).yml` | `git ls-tree` |

---

## 三、逐項自檢指令（`scripts/check_mac_env.sh` 建立前先用這個）

```bash
docker info >/dev/null 2>&1 && echo "✅ docker daemon" || echo "❌ docker daemon"
which ffmpeg  >/dev/null && echo "✅ ffmpeg"   || echo "❌ ffmpeg"
which mediamtx >/dev/null && echo "✅ mediamtx" || echo "❌ mediamtx"
ai/.venv/bin/python -c "import kafka,dotenv,boto3,av,tritonclient" 2>/dev/null \
  && echo "✅ ai/.venv 套件齊" || echo "❌ ai/.venv 缺套件"
.venv/bin/python -c "import ollama" 2>/dev/null && echo "✅ 根 venv ollama" || echo "❌ 根 venv 缺 ollama"
ls ai/triton_repo/rt_detr_onnx/1/model.onnx >/dev/null 2>&1 \
  && echo "✅ rt_detr_onnx 權重" || echo "❌ rt_detr_onnx 權重"
for m in yolo_pose rt_detr_onnx action_transformer; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:8010/v2/models/$m/ready")
  [ "$code" = "200" ] && echo "✅ triton $m" || echo "❌ triton $m (HTTP $code)"
done
curl -s -o /dev/null -w 'backend /docs → %{http_code}\n' http://127.0.0.1:8000/docs
curl -s -m 3 http://localhost:11434/api/version >/dev/null && echo "✅ ollama" || echo "❌ ollama"
```

---

## 四、WBS

狀態：`☐` 未做 / `☑` 完成 / `⚠` 卡住（原因寫在備註）

### P0 環境地基

| ID | 任務 | 驗收 | 狀態 | 備註 |
|---|---|---|---|---|
| T0-1 | 啟動 Docker Desktop | `docker info` 不報錯 | ☑ | 已確認 `linux/arm64` 原生，非模擬 |
| T0-2 | `git config core.hooksPath .githooks` | `git config core.hooksPath` 回 `.githooks` | ☑ | 每台機器一次，永久生效 |
| T0-3 | 安裝 ffmpeg 與 mediamtx | 兩者可執行 | ☑ | **這台沒有 Homebrew**，兩者都不在 PATH 上，走替代來源（見 T4-0）。自檢腳本已改成三種來源都認（PATH / `.env` / docker image）|
| T0-4 | 補 `ai/.venv`：`kafka-python-ng python-dotenv boto3 av tritonclient clearml onnxslim` | 自檢的 import 那行過 | ☑ | **踩過相依坑**：`tritonclient[all]` 在 arm64 macOS 只解到 2.36.0（釘 protobuf 3.20.3），與 onnxslim 要的 protobuf 7.x 打架。**解法：改裝 `tritonclient[http,grpc]>=2.50`** → 得到 2.71.0 + protobuf 6.33.6，三方共存。**不要用 `[all]`**（它拉的 cuda 相依在這台解不動）|
| T0-5 | 補根 `.venv`：`ollama` | `import ollama` 過 | ☑ | vlm_client 延遲 import 它 |
| T0-6 | 把第三節自檢寫成 `scripts/check_mac_env.sh` | 跑得動、輸出可讀 | ☑ | 每項對應一個 T 編號，看到第一個 ❌ 就從那接手 |
| T0-7 | `python3 scripts/check_guardrails.py` | 綠燈 | ☑ | 綠燈（掃 306 檔）。每個階段結束都要再跑一次，`check_mac_env.sh` 最後一段也會順手跑 |

### P1 Triton CPU on arm64（風險最高，先做）

| ID | 任務 | 驗收 | 狀態 | 備註 |
|---|---|---|---|---|
| T1-1 | `ai/.venv/bin/python ai/export_models.py`（**不帶 `--plan`**） | 三顆 `1/model.onnx` 產出 | ☑ | **`rtdetr-l.pt` 不會自動下載**（`export_models.py` 先檢查檔案就 fail），要手動撈：`curl -fL -o ai/rtdetr-l.pt https://github.com/ultralytics/assets/releases/download/v8.3.0/rtdetr-l.pt`（63MB）。產出：pose 38MB / detr 126MB / act 0.3MB |
| T1-2 | `rt_detr/1/model.onnx` hardlink 到 `rt_detr_onnx/1/model.onnx` | 檔案在 | ☑ | 匯出的 detr ONNX 介面 `images[1,3,640,640]→output0[1,300,6]`，與 `rt_detr_onnx/config.pbtxt` 完全對得上 |
| T1-3 | 起 CPU Triton | 三顆 `/ready` 都 200 | ☑ | **三顆全部載入成功**（Triton 2.62.0，arm64 原生）。指令見下方「T1-3 定案指令」|
| T1-3a | **必要前置**：`./ai/make_cpu_repo.sh` 產 `ai/triton_repo_cpu/` | 三個模型目錄都有 `config.pbtxt` + 權重 | ☑ | **不能直接用 `ai/triton_repo/`**：那裡的 `config.pbtxt` 寫 `instance_group kind: KIND_GPU`，沒 GPU 時三顆全 UNAVAILABLE，explicit 模式一顆倒全倒（`error: creating server`）。`make_cpu_repo.sh` 就是為此存在（sed 換成 `KIND_CPU`，權重走 hardlink，產物不進版控）|
| T1-4 | `.env` 補 `TRITON_POSE_URL` / `TRITON_DETR_URL`(→`rt_detr_onnx`) / `TRITON_ACT_URL` | `inference_test.py` 起得來、不報連線失敗 | ☑ | 已 append 到 `.env` 尾段 |
| T1-5 | 修 `ai/run_triton.sh` 的 bash 3.2 相容性 | 腳本跑得動 | ☑ | **macOS 內建 bash 是 3.2.57**（無 brew），`"$VAR）"` 這種「變數緊接全形字元」會被解析成變數名的一部分 → `unbound variable`。已把 4 處改成 `"${VAR}）"`。Linux bash 5 沒這問題，故此修改對另一台零影響 |

**T1-3 定案指令**（每次開機都要跑一次，`--rm` 容器不會自己回來）：

```bash
TRITON_GPUS=none HTTP_PORT=8010 GRPC_PORT=8011 METRICS_PORT=8002 \
  MODEL_REPO="$(pwd)/ai/triton_repo_cpu" \
  LOAD_MODELS="yolo_pose rt_detr_onnx action_transformer" ./ai/run_triton.sh
```

> **Triton image 是 20.4GB**（解壓後，佔 Docker 磁碟 85%）。首次 pull 很久，之後就在本地了。
> 不要用 `docker system prune -a` 隨手清，會把它一起清掉。

### P2 端到端主鏈（核心目標）

| ID | 任務 | 驗收 | 狀態 | 備註 |
|---|---|---|---|---|
| T2-1 | `docker compose up -d`（kafka / kafka-ui / backend / frontend） | 四個容器 healthy，`:8000/docs` 200 | ☑ | 四個都 running，Kafka healthy，backend consumer 已 join group 並訂到 `processed-reports`；frontend :80 也 200 |
| T2-2 | 確認後端裝置表可用 | `GET /devices` 撈得到 active 裝置 | ☑ | RDS 共用庫**已有 9 台**，`device_id=301` 有 `cam_in`/`cam_out`。P2 先不走 RTSP（要 MediaMTX，P4 才裝），改用 `SINGLE_SOURCE` 吃 mp4 |
| T2-3 | `SINGLE_SOURCE=ai/test_demo/test6.mp4` 跑推論，觸發跌倒 | 事件進 Kafka | ☑ | **實測 2.3~2.4 fps**（CPU，含節流）。一支 test6 觸發 2 筆事件、寫出 2 段 H.264 片段（`avc1 (OpenCV)`）、多人追蹤去重也有生效。指令見下方「T2-3 定案指令」|
| T2-4 | 確認後端 consumer 寫進 DB | **無 422**，`GET /events` 撈得到 | ☑ | `POST /events → 201 Created`，**零 422**。`GET /events` 回 200、撈到該筆，`event_type=fall`、`yolo_score=0.98`、`vlm_summary` 有完整中文判讀 |
| T2-5 | 前端事件中心看得到那筆 | 卡片出現 | ⚠ | **使用者已登入成功**（後端 log：`POST /login 200` → `GET /events 200`，來源 `172.19.0.5` 是前端容器的 nginx），代理鏈全通。**只剩卡片視覺確認**。原本卡點如下：`GET /events` 未帶 token 一律回 `{"detail":"Not authenticated"}`，後端接的是共用 RDS，不自行 `POST /register` 建帳號污染組員的庫。nginx 代理路徑已確認正確（`/api/events` → 後端 `/events`，`/api/stream` 另開一條關掉 buffering 給 SSE）。**要使用者提供組員給的帳密**，或明確同意在共用庫建一個測試帳號 |
| T2-6 | 拿到 `S3_RW_*` 金鑰後補 `.env` + `CLIP_S3_BUCKET` | 前端**點得開影片** | ☑ | `bucket=aipe03-3` / `region=ap-northeast-1` / `prefix=videos`。**bucket 與 region 都是查出來的**：金鑰無 `ListAllMyBuckets` 權限，改用 `head_bucket` 的 `x-amz-bucket-region` header 拿 region。已照 [`CHANGELOG-STAGES.md`](CHANGELOG-STAGES.md) 第 1 項先驗權限（Put/Head/Get/Delete 四通）再設 bucket。實跑：2 段片段上傳成功（674KB / 427KB），**後端唯讀金鑰簽出的 presigned URL 實測 HTTP 206 + `Content-Type: video/mp4` + 檔頭 `ftypisom`** |

### P3 VLM 二審

| ID | 任務 | 驗收 | 狀態 | 備註 |
|---|---|---|---|---|
| T3-1 | `VLM_MODEL_NAME=qwen2.5vl:7b` | — | ☑ | `vlm_client.py:21` 走 `os.environ`，**不讀 `.env`**，一定要 export 或寫在指令前面 |
| T3-2 | 根 venv 跑 `ai/vlm_worker.py` | 監聽 `nursing-home-alerts` 不報錯 | ☑ | **必須 `cd ai` 再跑**（它 `import uncertainty_router` / `vlm_client`，都是同目錄的兄弟模組）。指令見下方 |
| T3-3 | 造一次事件走慢速道 | `vlm_summary` 有文字、進 `processed-reports` | ☑ | **VLM 一次判讀 24.97 秒**（qwen2.5vl:7b 在 M2 Pro 上）。判讀內容正確（「一名男性躺在地上」）|
| T3-4 | ⚠ 啟動順序陷阱 | — | ☑ | `vlm_worker` 的 consumer 是 `auto_offset_reset='latest'` + 固定 group id（`vlm-brain-cluster`）→ 要驗二審，**一定先起 vlm_worker，再跑推論**。**⚠️ 2026-07-30 補正**：`latest` 只在 **group 首次建立**時決定起點；group 一旦存在就照 committed offset 走，**worker 沒開時累積的事件下次啟動會全部補做**（實測 T4-4 循環推流留下 LAG=6，等於開機先卡 2.5 分鐘再灌 6 筆假事件進 DB）。查積壓：`docker exec nh-kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group vlm-brain-cluster`；要丟掉就把 `--reset-offsets --to-latest --execute` 接上去（**group 不能有 active consumer**）|

**T2-3 / T3-2 定案指令**（順序不能反，見 T3-4）：

```bash
# 1) 先起 VLM 二審 worker（另開一個終端，用根 .venv）
cd ai && VLM_MODEL_NAME=qwen2.5vl:7b ../.venv/bin/python -u vlm_worker.py

# 2) 再跑推論（用 ai/.venv）
HEADLESS=1 SINGLE_SOURCE=ai/test_demo/test6.mp4 DETR_EVERY_N=5 \
  ai/.venv/bin/python -u ai/inference_test.py
```

> **`-u` 不要省**：Python 的 stdout 在非終端機時是整塊緩衝，沒有 `-u` 會讓你以為程式卡住了
> （實際在跑，只是訊息還沒吐出來）。同理，背景執行時**不要**接 `| tail`，那會憋到程式結束才有輸出。

### P4 串流（前端四宮格 + 偵測畫面）

| ID | 任務 | 驗收 | 狀態 | 備註 |
|---|---|---|---|---|
| T4-0 | 取得 ffmpeg 執行檔與 mediamtx | 兩者可執行 | ☑ | **全程免 sudo、免 Homebrew**。ffmpeg：`imageio-ffmpeg 0.6.0` 附的靜態版 **ffmpeg 7.1 / arm64**，含 `libx264`（推流要）與 `h264_videotoolbox`（硬體編碼）。路徑已寫進 `.env` 的 `DETECT_STREAM_FFMPEG`，實測 `detect_publisher.ffmpeg_path()` 讀得到。mediamtx：`bluenviron/mediamtx:latest` docker image（**linux/arm64 原生**）已拉。⚠️ ffmpeg 路徑**帶版號**（`ffmpeg-macos-aarch64-v7.1`），升級 imageio-ffmpeg 後要重取，重取指令寫在 `.env` 該段註解裡 |
| T4-1 | `cp streaming/mediamtx.yml.example streaming/mediamtx.yml` 並填設定 | 檔案在（**不進版控**）| ☑ | 與範本共 **4 處差異**，檔內都標了「Mac 差異」註解：①`authHTTPAddress` 改 `host.docker.internal`（容器內 `127.0.0.1` 是容器自己）②開 `api: yes` + `apiAddress: :9997`（範本沒開，但 T4-2 驗收要它）③補 `webrtcAdditionalHosts: [192.168.54.102]`（容器網卡只有 172.x，瀏覽器連不到 → 畫面永遠轉圈）④`cam_in` 改 `source: publisher`（沒攝影機）|
| T4-2 | 起 MediaMTX，`.env` 設 `MEDIAMTX_BASE_URL=http://<本機區網IP>:8889` | `:9997/v3/paths/list` 撈得到頻道 | ☑ | **MediaMTX v1.19.3 / linux arm64 原生**，8 個頻道全註冊（`ready=False` 正常，還沒人推流）。後端讀到並組出 `http://192.168.54.102:8889/cam_in/whep`。**auth 迴路實測通**：WHEP 未帶權杖 → MediaMTX 打後端 `/streams/auth` → 401「串流權杖無效」→ 正確拒絕 |
| T4-3 | ffmpeg 推 mp4 當 `cam_in` | 該頻道 `ready: true` | ☑ | `test6.mp4` 本身就是 **H.264**（不是 AV1），所以 `-c:v copy` 直接轉推、不必轉碼。`cam_in` → `ready=True` / `tracks=['H264']`。不要用 WHEP 狀態碼判斷，會全部誤判成有畫面 |
| T4-4 | `DETECT_STREAM=1` 跑推論 | 前端切「偵測」看得到骨架框 | ☑ | `cam_out` → `ready=True`。**直接從 `cam_out` 抓幀驗證**（比看狀態可信）：骨架、`person 0.84/0.53/0.75/0.66` 框、紅色 `FALL DETECTED!` 邊框、VLM 狀態列全都在 |

**T4-2 定案指令**（`--restart unless-stopped`，開機後 Docker 起來它就自己回來；`docker run` 不是 compose）：

```bash
docker run -d --name nh-mediamtx --restart unless-stopped \
  -v "$(pwd)/streaming/mediamtx.yml:/mediamtx.yml:ro" \
  -p 8554:8554 -p 8889:8889 -p 9997:9997 -p 8189:8189/udp \
  bluenviron/mediamtx:latest
```

**T4-3 / T4-4 定案指令**（順序不能反：`cam_in` 沒畫面時推論會一直重連拉不到東西）：

```bash
# 1) 推 mp4 進 cam_in（-c:v copy 不轉碼；-stream_loop -1 無限循環）
FF=$(grep '^DETECT_STREAM_FFMPEG=' .env | cut -d= -f2-)
"$FF" -re -stream_loop -1 -i ai/test_demo/test6.mp4 \
  -an -c:v copy -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam_in

# 2) 跑推論，畫框後推回 cam_out（另開終端）
HEADLESS=1 DETECT_STREAM=1 ai/.venv/bin/python -u ai/inference_test.py
```

> ⚠️ **`SINGLE_SOURCE` 與 `DETECT_STREAM` 互斥，這是 T4-4 最容易卡住的地方。**
> `inference_test.py:1192` 的 `_overrides_replace_all`：設了 `SINGLE_SOURCE` 就整包換掉
> `camera_channels` 並**跳過打後端**，而 `detect_channels` 只有問後端才拿得到（它是資料庫欄位）
> → `detect_channels` 永遠是空 dict → 設了 `DETECT_STREAM=1` 也**完全不會推**，且不會有任何錯誤訊息。
> 要推 `cam_out` 就**不能設 `SINGLE_SOURCE`**，改讓它走預設的 `CAMERA_SOURCE=backend` 從 `cam_in` 拉流。
>
> ⚠️ **無限循環會反覆觸發事件並上傳 S3**（每輪約 2 筆）。驗完畫面就把 ffmpeg 與推論都停掉。
>
> ℹ️ 後端有 4 台 active 裝置，但這台只有 `cam_in` 有畫面，所以 `phone_a/b/c` 三路會刷
> `404 Not Found` + 指數退避重連（上限 30s）。**這是預期行為不是故障**，那三路是給手機推流用的。

> **`-p 8189:8189/udp` 不要漏**（WebRTC 的 ICE 走 UDP，漏了會協商成功但畫面不動）。
> macOS 的 Docker Desktop **不支援 `--network host`**，所以埠要一個一個開。
> **換 Wi-Fi 或重開機後區網 IP 會變**，要同步改兩個地方：`streaming/mediamtx.yml` 的
> `webrtcAdditionalHosts` 與 `.env` 的 `MEDIAMTX_BASE_URL`（查 IP：`ipconfig getifaddr en0`）。

### P5 MLOps 迴路

| ID | 任務 | 驗收 | 狀態 | 備註 |
|---|---|---|---|---|
| T5-1 | 建 `ai/docker-compose-clearml.mac.yml` override（覆蓋 `platform` / ES heap）| 原檔一行不動 | ☑ | 原檔確認未動。**查了 registry manifest 才知道只有 `clearml/server` 需要模擬**：它是 amd64-only，而 `elasticsearch:7.17.9` / `mongo:5.0.26` / `redis:6.2-alpine` **都有 arm64**（R3 是誤判）→ 三個依賴原生跑，只有 apiserver/fileserver/webserver 加 `platform: linux/amd64`。另把 ES heap 從 2g 砍到 1g（記憶體帳見備註）。`compose config` 驗過合併結果正確 |
| T5-2 | `docker compose -p ai -f ai/docker-compose-clearml.yml -f ...mac.yml up -d` | `:8008/debug.ping`、`:8085` 活著 | ☑ | 六個容器全 Up。`debug.ping` 回 `result_code: 200`、web `:8085` 200、fileserver `:8081` 200。**`-p ai` 不能省**，volume 名靠它。⚠️ **這台的六個 volume 全是新建的**（log 顯示 `Created` 不是複用）——原 compose 檔頭「這台已經有一份跑過的 ClearML 資料」是在講 5060 Ti 那台，**這台是空的，沒有既有實驗記錄** |
| T5-3 | 起 Label Studio（`-p ai`）| `:8082` 進得去 | ☑ | `heartexlabs/label-studio:latest` **原生 arm64**。`:8082` 回 302（導向登入頁）、`/user/login` 200，記憶體 0.33 GB。⚠️ **起之前要先 `mkdir -p ai/active_learning_dataset`**：那是 bind mount 來源，不存在時 Docker 會自作主張建一個 **root 擁有**的空目錄，之後容器內寫不進去。同 T5-2，`ai_lsdata` volume 也是新建的 → **這台沒有既有標註資料** |
| T5-4 | `cp ai/clearml.conf.example ~/clearml.conf` 填 credentials | SDK 認證得過 | ☑ | **實測認證成功**（`users.get_current_user` → 200，身分 `ychsieh`），三個 server 位址都對得上。S3 區段（`sdk.aws.s3`）從 `.env` 的 `S3_RW_*` 自動填入並驗過 SDK 讀得到 → T5-7 上傳權重可用。⚠️ 檔案在**家目錄** `~/clearml.conf`，不是專案內（SDK 寫死只讀這個位置）；含金鑰，權限設成 `600`、不進版控 |
| T5-5 | `python ai/inference_to_labelstudio_sdk.py` 推預標註 | LS 裡看得到待審任務 | ⚠ | **已修掉一個會直接 404 的 bug**（見下）。**卡在三個前置**，都是「LS 網頁上的東西」而這台的 LS 是全新的：①要先註冊帳號並填 `.env` 的 `LABEL_STUDIO_USERNAME/PASSWORD`（**跟 ClearML 是兩套系統**，帳密不共用）②要有專案 id=1 且 label_config 含 `person/chair/sofa/bed/tv` ③專案裡要有 task。**腳本不建專案、不上傳圖**，只認已存在的。素材可用 `ai/snapshots/` 的 14 張推論證據快照 |
| T5-6 | `clearml-agent daemon --queue default`（host 原生，**不帶 `--gpus`**）| agent 咬得到單 | ☐ | |
| T5-7 | `TRAIN_DEVICE=cpu TRAIN_EPOCHS=1 python ai/submit_task.py` | ClearML 有任務、跑完出權重 | ☐ | 見 D8，只驗流程 |
| T5-8 | `python ai/model_deployment_agent.py` 熱部署 | Triton 載到新版本、推論吃到 | ⚠ | **熱部署機制本身已在 Mac 驗通（走 AcT/`action_transformer`）**，但 `model_deployment_agent.py` 這支還不能用（4 個障礙見下）。實測全鏈：`act_s42_st1.pth` → ONNX（PyTorch 比對誤差 1.19e-06）→ 熱載 v1→v2（HTTP 200）→ **線上推論輸出與本地權重逐位吻合（4.77e-07）** → 回滾 v2→v1（HTTP 200）|
| T5-8a | `model_deployment_agent.py` 要能在 Mac 跑，需改的 4 處 | 這支在 Mac 上跑得完 | ☑ | **①②④ 已改並實測跑通全自動部署**：`build_plan` 改成依 `config.pbtxt` 的 `platform` 決定（`tensorrt_plan` 才編引擎）——**判斷依據是「這顆模型要什麼格式」不是「這台有沒有 GPU」，同一份 code 兩台都對**；`TRITON_REPO_DIR` 改可覆蓋（線上掛的是 `triton_repo_cpu`）；兩個 config 補 `version_policy`（鎖 v1＝現狀，安全）。`do_rollback` 也一併修（原本硬檢查 `model.plan`，ONNX 路線會被誤判成不能回滾）。③ 見 T5-8b |
| T5-8b | 讓部署支援 AcT（`action_transformer`）| — | ☐ | `export_onnx()` 寫死 `RTDETR(pt_path).export()`，AcT 是自訂 PyTorch 模型不適用。**卡在架構定義的單一來源**：AcT 架構在 `inference_test.py:390`，要嘛 import 它（會連帶啟動 Triton client，有副作用）、要嘛再抄一份（違反單一來源）。乾淨解是把 `ActionTransformer` 抽成獨立模組讓兩邊 import —— 但那動到跌倒主鏈的核心檔案，要另外評估 |
| T5-9 | 收尾：`python3 scripts/check_guardrails.py` + 更新 `RUN_ON_MAC.md` | 綠燈、文件與實況一致 | ☑ | 護欄綠燈（308 檔）。**新建 [`RUN_ON_MAC.md`](../RUN_ON_MAC.md)** —— 定位是「每天開機的操作手冊」（啟動順序／埠表／症狀→解法），與本檔互補不重複。逐項驗過文件裡提到的檔案、`.env` 鍵、`run_triton.sh stop` 都真的存在。**順手更正 `CONTRIBUTING.md` 第四節**：原文說「把 `--gpus all` 拿掉自己起一份」已過時（`run_triton.sh` 本來就支援 `TRITON_GPUS=none`），且漏了 `KIND_GPU` 與 `tensorrt_plan` 兩個必撞的點；同時把 Mac 兩份文件接上入口（先前沒有任何地方連得到）|

---

## 五、執行紀錄（每次工作後追加，最新在最上面）

| 日期 | 做了什麼 | 結果 / 實際數字 |
|---|---|---|
| 2026-07-30 | **T5-8a 完成**：`model_deployment_agent.py` 在 Mac 上跑通全自動熱部署 | 實測 `--from-pt` 部署 T5-7 的權重 → 跳過 trtexec → v1→v3 熱載 READY → `--rollback` 兩次回到 v1，版控的 `config.pbtxt` 全程沒被動到。**踩到一個症狀極誤導的坑**：Triton 跑著時跑 `make_cpu_repo.sh`（`rm -rf` 重建）會讓容器的 bind mount 指向死 inode，`/models` 變空，但已載入的模型 `/ready` 照樣 200，只有 reload 失敗 → 已寫進 `RUN_ON_MAC.md` |
| 2026-07-30 | **T5-9 收尾**：新建 `RUN_ON_MAC.md`、更正 `CONTRIBUTING.md` 第四節、停背景 agent | 護欄綠燈（308 檔）。文件入口鏈補起來：`CLAUDE.md` → `CONTRIBUTING.md` 第四節 → `RUN_ON_MAC.md` / `MAC_SETUP_WBS.md`（先前兩份 Mac 文件沒有任何地方連得到）|
| 2026-07-30 | **T5-6 / T5-7 完成，T5-8 熱部署機制驗通**（改走 AcT 而非 rt_detr）| agent 咬單 → CPU 訓練 **32.2 秒/epoch** → mAP50 0.535 未過門檻 0.8 → 權重上 S3 並標 `below-gate`。熱部署：AcT `.pth` → ONNX → 熱載 v1→v2 → **線上輸出與本地權重逐位吻合（4.77e-07）** → 回滾成功。踩到 3 個坑：uv 建的 venv **沒有 pip**（agent 必掛）、torch 2.13 匯出**外部權重檔**、版控 `config.pbtxt` 不能鎖新版（會弄倒另一台）|
| 2026-07-30 | **T5-3 / T5-4 完成**，T5-5 修掉一個寫死的模型名 | Label Studio 原生 arm64、`:8082` 302；`~/clearml.conf` 認證過（身分 `ychsieh`）。**`inference_to_labelstudio_sdk.py:347` 寫死 `/rt_detr`**，在無 GPU 機器上必 404 —— 改成沿用既有的 `TRITON_DETR_URL` 契約（同 `inference_test.py:419`），沒設時 fallback 回原值，對 5060 Ti 零影響。順手修掉 `check_mac_env.sh` **5 處** bash 3.2 `$VAR）` 地雷（全在失敗分支裡，最需要時才會炸）|
| 2026-07-30 | **T5-1 / T5-2 完成**：ClearML server 六服務起在 Mac（override 檔隔離差異）| 查 manifest 推翻 R3：**只有 `clearml/server` 是 amd64-only**，ES/mongo/redis 都有 arm64 → 三個依賴原生跑。`debug.ping` 200、web 8085 200、files 8081 200。記憶體 **2.84 GB / 7.75 GB**，比預想寬鬆（R8 解除）|
| 2026-07-30 | **修 R7**：`backend/core/database.py` 補連線池保鮮（`pool_pre_ping` + `pool_recycle`）| A/B 實測：無 pre_ping 噴 `SSL connection has been closed unexpectedly`，有 pre_ping 自動汰換成功。後端 **176 tests passed**。容器已 rebuild，`engine.pool._pre_ping=True` |
| 2026-07-30 | 收尾清理：Kafka offset 快轉、刪掉循環測試的 S3 副產品 | `vlm-brain-cluster` LAG 6 → 0；刪 2 段循環測試 clip，T2-6 的 2 段驗證檔保留。順手補正 T3-4 對 `auto_offset_reset` 的理解 |
| 2026-07-30 | **T4-3 / T4-4 完成，P4 收工**：mp4 → `cam_in` → 推論畫框 → `cam_out` | 兩個頻道都 `ready=True`。從 `cam_out` 抓幀確認骨架框與 `FALL DETECTED!` 都在。**抓到 `SINGLE_SOURCE` 與 `DETECT_STREAM` 互斥**（靜默不推、無錯誤訊息），已寫進定案指令的警告 |
| 2026-07-30 | **T4-1 / T4-2 完成**：MediaMTX 起在 docker，auth 迴路打通 | v1.19.3 arm64，8 頻道全註冊。踩到 3 個「MediaMTX 在容器裡」專屬的坑（`127.0.0.1`／ICE 位址／API 沒開），都寫進 `mediamtx.yml` 的註解。**決策：串流不接攝影機，影像輸入一律 mp4** |
| 2026-07-30 | **T2-6 打通**：重跑 test6.mp4，全鏈驗證 S3 影片 | 2 筆事件 → clip 上傳 `s3://aipe03-3/videos/`（674KB / 427KB）→ VLM 二審 **32.22s / 23.30s** → `POST /events` **201 ×2，零 422** → presigned URL **HTTP 206 / video/mp4 / `ftypisom`**。**順帶抓到後端 bug**：`create_engine` 缺 `pool_pre_ping`，RDS 閒置斷線後第一個請求必 500（見第六節 R7）|
| 2026-07-30 | **T2-6 設定完成**：金鑰填入 `.env`，bucket / region 靠實測問出來（不是猜的）| 讀寫金鑰**沒有 `ListAllMyBuckets` 權限**（最小權限，正常），改用 `head_bucket` 的 `x-amz-bucket-region` header 拿到 `ap-northeast-1`；bucket 名 `aipe03-3` 出自 [`CHANGELOG-STAGES.md`](CHANGELOG-STAGES.md) 第 1 項。Put/Head/Get/Delete **四項全通** |
| 2026-07-30 | **T4-0 完成**（P4 前置）：免 Homebrew 取得 ffmpeg 與 mediamtx；自檢腳本補 P4 段 | ffmpeg **7.1 arm64**（imageio-ffmpeg 0.6.0，含 libx264 / videotoolbox），路徑寫進 `.env`，`detect_publisher.ffmpeg_path()` 讀得到；`bluenviron/mediamtx:latest` **linux/arm64** 已拉。**T2-5 卡住**：`GET /events` 要登入，手上沒帳密 |
| 2026-07-30 | **P2 + P3 打通**：容器四件套 → 推論 → Kafka 慢速道 → VLM 二審 → 後端 → DB | 推論 **2.3~2.4 fps**（CPU）；一支 test6.mp4 出 **2 筆事件 + 2 段 H.264 片段**；VLM 判讀 **24.97 秒/次**；`POST /events` **201 Created，零 422**；`GET /events` 撈得到，`vlm_summary` 中文判讀正確 |
| 2026-07-30 | **P1 打通**：三顆模型在 arm64 CPU Triton 全部 ready | Triton 2.62.0 原生 arm64。踩到 `KIND_GPU` → 用 `make_cpu_repo.sh` 解。image 20.4GB |
| 2026-07-30 | P0：Docker / 兩個 venv / 自檢腳本；修 2 個版控檔的 Mac 相容性 | 護欄綠燈（掃 306 檔）。ffmpeg/mediamtx 因無 brew 延到 P4 |
| 2026-07-30 | 開分支 `feat/mac-local-runbook`、產出本 WBS。環境調查完成（第二節） | — |

---

## 六、未確認的假設與風險

| # | 風險 | 現在的判斷 | 撞到了怎麼辦 |
|---|---|---|---|
| ~~R1~~ | ~~arm64 Triton image 能否啟動~~ | **已解除**：25.10-py3 arm64 原生啟動正常，onnxruntime backend 完整，三顆全載入 | — |
| ~~R2~~ | ~~CPU 推論太慢~~ | **已量測：2.3~2.4 fps**（`DETR_EVERY_N=5`）。跌倒判定照樣成立（連續 4 幀），事件、片段、追蹤去重都正常 | fps 不要跟 5060 Ti 比（`ai/FPS_NOTES.md`）|
| ~~R3~~ | ~~`elasticsearch:7.17.9` 是否有 arm64~~ | **已解除**：`docker manifest inspect` 查到它**有 `linux/arm64`**，原生可跑，不必換 8.19.9。同批查證：`mongo:5.0.26` ✅、`redis:6.2-alpine` ✅、**`clearml/server:latest` 是 amd64-only**（唯一要模擬的）| — |
| ~~R8~~ | ~~ClearML 六個服務 + 現有容器會不會爆記憶體~~ | **已量測，比預想寬鬆**：六個服務**閒置時只佔 1.66 GB**，全部容器合計 **2.84 GB / 7.75 GB（剩 4.91 GB）**。大頭是 `clearml-elastic` 1.28 GB（heap 砍到 1g 的效果），**三個 Rosetta 模擬的 `clearml/server` 加起來才 0.24 GB**——模擬吃的是 CPU 不是記憶體 | 閒置額度夠，`nh-triton` / `nh-kafka-ui` **可以開回來**。真正的壓力點在 T5-7 重訓（CPU + 資料載入），到那步再看 |
| R4 | RT-DETR 在 MPS 上能否訓練 | **不知道** | 不碰，照 D8 走 CPU |
| R5 | `model_deployment_agent.py` 是照 TensorRT 流程寫的，Mac 只有 ONNX | **已查證：環境變數繞不過去，必須改 code**（4 處，見 T5-8a）。但**熱部署機制本身在 Mac 是通的** —— 換走 `action_transformer`（`onnxruntime_onnx`）而非 `rt_detr`（`tensorrt_plan`）就完全不需要 GPU/trtexec | 改 `build_plan` 的觸發條件為「看 `platform` 而不是看機器」，同一份 code 兩台都對 |
| R9 | **不能在版控的 `config.pbtxt` 加 `version_policy` 鎖新版本** | **實測確認的地雷**：`ai/triton_repo/*/[0-9]*/` 在 `.gitignore` 裡（權重不進版控），所以另一台 pull 到「鎖 v2 的設定檔」卻只有 `1/` 目錄 → 該模型 UNAVAILABLE → **explicit 模式一顆倒全倒，整台 Triton 起不來**（`rt_detr` 踩過，`triton_repo/README.md` 有事故記錄）| 版本鎖只改 `triton_repo_cpu/`（產物、不進版控）。要動版控那份，權重必須同時有辦法讓對方拿到 |
| R10 | torch 2.13 匯出的 ONNX 預設是**外部權重檔** | 實測踩到：產出 `model.onnx` + `model.onnx.data`，只放前者 → Triton 報 `cannot get file size: ...model.onnx.data`、版本 UNAVAILABLE | 匯出後用 `onnx.save(..., save_as_external_data=False)` 併回單一自包含檔，與 `export_models.py` 產的 v1 格式一致 |
| ~~R6~~ | ~~唯讀 S3 金鑰上傳會 403~~ | **已解除**：`S3_RW_*` 已填並實測四項全通，T2-6 完成 | — |
| ~~R7~~ | ~~後端 `create_engine` 缺 `pool_pre_ping=True`~~ | **已修並驗證**（2026-07-30）：`backend/core/database.py` 補 `pool_pre_ping=True` + `pool_recycle=1800`。**A/B 實測**：同一段「把連線放回池裡→從 DB 端 `pg_terminate_backend`→再借一次」的劇本，無 pre_ping 噴 `OperationalError: SSL connection has been closed unexpectedly`，有 pre_ping 自動換新連線成功。後端 176 個測試全過 | **這是後端組的檔案，改動尚未 commit**。不是 Mac 專屬，5060 Ti 那台一樣會中，要另開分支 + PR 知會後端組 |

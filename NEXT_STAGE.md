# 下一階段待辦

各項標題前的【】標記目前狀態，一眼掃過去就知道要不要動：
【已完成】＝驗證過了，不用重做；【待辦】＝還沒做；
【本輪不執行】＝已決定這輪不做（理由見該項）；【只出設計】＝方案已定、實作留給後續。

**2026-07-28 這一輪做了什麼**：S3 上傳接通（前端終於看得到影片）、六大防線收斂成
「跌倒 + 巡檢」並把規則寫成護欄擋得住的硬規定、產出 Triton GPU vs CPU 對照數據、
出了 Prometheus 導入設計、**agent P2 後端記錄 + 前端顯示已完成並合併**（PR #14），
過程中順手修了 VLM（`llava:latest`）同張圖同提示會隨機拒答的問題。

**同日稍晚**：接回 main 的 `stream_channel` 改名（後端原本三個端點全 500，事件卡在
Kafka 進不了資料庫）、補上偵測畫面推流讓前端「偵測」真的看得到姿態框，
並確立「**事件片段與快照刻意不畫框**」為組長決策（見第 8 項，不要修好它）。

---

## 待辦總覽

| # | 項目 | 狀態 |
|---|---|---|
| 1 | S3 上傳接通 | ✅ 已完成並實測 |
| 2 | 六大防線收斂 + `ai/modules/` 白名單 | ✅ 已完成 |
| 3 | Triton GPU vs CPU 對照 | ✅ 已完成，報告見 `ai/BENCHMARK_GPU_VS_CPU.md` |
| 4 | Prometheus 導入 | 📐 只出設計，未接線 |
| 5 | 事件冷卻計時器 | ⏸ 本輪不執行（卡多人追蹤）|
| 6 | agent P2（後端記錄 + 前端顯示 AI 判斷）| ✅ 已完成並合併（PR #14） |
| 7 | 接回 main 的 `stream_channel` 改名（解後端全面 500）| ✅ 已完成並實測 |
| 8 | 偵測畫面推流 `cam_out`（前端「偵測」畫面）| ✅ 已完成並實測 |

第 5、6 兩項互不依賴，可分頭進行。

---

## 7.【已完成】接回 main 的 `stream_channel` 改名 —— 後端從全面 500 救回來

`devices` 的欄位改名（`stream_url` → `stream_channel`，`origin/main` `51871e5`，PR #15）
已經施作在**共用的正式 RDS** 上，但本測試分支的後端 model 還停在舊名字，導致
`GET /devices`、`GET /events`、`POST /events` **全部 500**——前端事件中心整頁空白，
AI 偵測到的跌倒卡在 Kafka 進不了資料庫（20 分鐘內重試失敗 68 次）。

**壞得很安靜**：四個容器全綠、AI 端 log 一路正常，只有翻後端日誌才看得到。

合併 `origin/main` 之後，還要補三個 **git 自動合併成功、但語意已壞**的地方——兩邊改的是
同一個檔的不同段落，diff 上看不出問題，一執行就 `TypeError: 'stream_url' is an invalid
keyword argument`：`devices/router.py` 的 `POST /devices`、`init_db.py` 的種子、
`test_devices_create.py`。種子同時改成種**頻道名**而非完整 `rtsp://` 網址（種完整網址
正是這次改名要根除的錯誤用法：那種位址只在填寫者自己的機器上有效）。

順手修掉的第二個 bug：`TRITON_*_URL` 是全檔唯一還用 `os.environ.get` 直接讀的設定，
繞過了 `cfg()`，所以寫進根目錄 `.env` **完全沒有效果**；加上預設值是被 backend 佔用的
8000，後果是每一幀都打到 FastAPI 拿 404 然後靜默降級——影片照跑、FPS 照印、零紅字，
**姿態偵測全程失效**。已改走 `cfg()`、預設 8010。

---

## 8.【已完成】偵測畫面推流：前端「偵測」看得到真的姿態框

kelly 已經做好前端「即時／偵測」切換鈕、後端 `stream_channel_detect`、MediaMTX 的
`cam_out` 頻道，但 `cam_out` 是 `source: publisher`（開著門等人推），**沒有任何程式在推**，
所以切到「偵測」永遠是空的。設定檔註解原本寫「正式來源是 albert 的推論程式，尚未實作」。

新增 [`ai/detect_publisher.py`](ai/detect_publisher.py)，把 `inference_test.py` 早就畫好的
`annotated_frame` 多開一條出口推回 MediaMTX：開一支 **ffmpeg 子程序**，stdin 收 BGR 原始幀，
編成 H.264 推進去。與 kelly 的 `start-fake-detect.ps1` 走同一條路（ffmpeg → rtsp），
差別只在畫面來源從「ffmpeg 自己畫的固定紅框」換成「AI 真正畫的骨架與框」。

**需要機器上裝 ffmpeg**（`sudo apt install ffmpeg` / `winget install Gyan.FFmpeg`）。
裝在非標準位置時可用 `DETECT_STREAM_FFMPEG` 指定完整路徑。找不到就不推流並印訊息，
其餘功能完全不受影響（三種降級路徑都實測過）。

### ⚠️ 事件片段與快照「刻意」維持無框，不要修好它

**這是組長的決策，不是缺陷**：警示彈窗要人當下確認，畫面上有框會干擾判讀。要看框請走
即時串流的「偵測」那一半，UI 上已經分好了。

所以：**不要把 `annotated_frame` 接進 `write_event_clip()` 或快照存檔**。
兩條路實測確認是分開的——同一次跑，`cam_out` 讀回來有骨架與 `person 0.90` 的框，
事件片段同一時段的畫面乾淨無框。

### 實測踩到的坑：時間戳這組參數兩個都不能少

`-use_wallclock_as_timestamps 1` 與 `-fps_mode cfr` 要一起用：

- **少了 wallclock**：rawvideo 照 `-r` 推算時間，但推論的實際張數低於名目值且會變動，
  串流會變慢動作、延遲一路累積不會回頭。
- **少了 CFR 整流**：光靠真實時鐘，編碼器以 `-r` 的刻度記時間戳，推論速度一抖動、
  相鄰兩幀擠進同一格就 DTS 撞號，整條推流直接斷掉。

**這個坑值得記**：平順推流時完全正常（連推兩百多幀沒事），只有在速度抖動的那一瞬間
才炸。驗證時要刻意用「爆量＋停頓」的不規則節奏測，等速測試看不出來。
實測 200 幀不規則節奏：送出 187、丟 13、零中斷。

### 開關與已知限制

- `DETECT_STREAM=1` 才推，未設＝位元級原行為（已實測）。
- 需要 ffmpeg；沒裝、或 `DETECT_STREAM_FFMPEG` 指到不存在的路徑，都會印訊息後略過推流
  （兩種都實測過，不影響其他功能）。
- 與 `NO_RENDER=1` 互斥（那個開關跳過畫框，等於沒畫面可推），偵測到會明講並停用。
- 推流的 FPS 成本：10.1（未推流 10.5~12），約在雜訊範圍邊緣，可接受。
- 這台機器沒有 MediaMTX 也沒有 ffmpeg，驗證時是臨時抓 MediaMTX v1.19.3 與免安裝的
  靜態 ffmpeg 7.0.2 起在本機跑的。要在這台常態使用，得把兩者都裝好並設
  `MEDIAMTX_BASE_URL`（目前刻意留空＝灰色占位框）。

---

## 1.【已完成】S3 上傳接通 —— 前端看得到事發影片了

### 原本卡在哪（記錄用）

舊版這裡寫的是「要去問後端組／AWS 管理者有沒有 `PutObject` 權限」。**這個前提是錯的**：
根 `.env` 早就有一組標明「AWS S3 讀寫」的 `S3_RW_*` 金鑰，只是**全 repo 沒有任何程式碼
讀它**——`ai/inference_test.py` 讀的仍是唯讀那組。真正的缺口是「金鑰名稱對不上」＋
「`CLIP_S3_BUCKET` 沒設」，不是權限。

### 做了什麼

1. **先驗權限再改設定**（順序不能反：設了 bucket 但沒權限＝上傳失敗但壞連結已經發出去，
   比「誠實地沒有影片」更難查）。用 `S3_RW_*` 對 `s3://aipe03-3/videos/` 實跑
   put → head → get → delete，**全通**。
2. `ai/inference_test.py` 的 S3 憑證改成**讀寫優先、舊名 fallback**：
   ```python
   _S3_REGION     = cfg("S3_RW_REGION")            or cfg("S3_REGION")
   _S3_ACCESS_KEY = cfg("S3_RW_ACCESS_KEY_ID")     or cfg("ACCESS_KEY_ID")
   _S3_SECRET_KEY = cfg("S3_RW_SECRET_ACCESS_KEY") or cfg("SECRET_ACCESS_KEY")
   ```
   留 `or` fallback 的原因：沒設 `S3_RW_*` 的機器（Mac、CI）行為與改動前完全一樣。
3. `.env` 補上 `CLIP_S3_BUCKET=aipe03-3` 與 `CLIP_S3_PREFIX=videos`。

### 實測驗證（不是推論）

跑一次真管線觸發跌倒後：

```
🎬 [Room_301_Bed] 事件片段已寫入（187 幀 @ 24.0fps）：ai/clips/clip_Room_301_Bed_20260728_003214.mp4
📦 [Room_301_Bed] 片段已上傳：s3://aipe03-3/videos/clip_Room_301_Bed_20260728_003214.mp4
```

Kafka 上的 payload（`nursing-home-alerts`，欄位一個字沒動）：

```json
{"device_id": 301, "event_type": "fall",
 "clip_path": "s3://aipe03-3/videos/clip_Room_301_Bed_20260728_003214.mp4",
 "detected_at": "...", "snapshot_path": "...", "image_filename": "...",
 "yolo_score": 0.9427, "yolo_threshold": 0.45, "vlm_summary": "..."}
```

用**後端自己的程式碼**（容器內 `core.s3.generate_presigned_url`）換發網址：

```
presigned URL: 已產生
GET → HTTP 200  Content-Type=video/mp4  bytes=995737
非 s3:// 的欄位: None      ← 舊事件（本地路徑）仍照樣回 null，向下相容沒破
```

### 給後端組的名稱清單

| 項目 | 值／名稱 | 後端要做什麼 |
|---|---|---|
| bucket / prefix | `aipe03-3` / `videos/` | — |
| **後端讀的憑證變數（不動）** | `S3_REGION`、`ACCESS_KEY_ID`、`SECRET_ACCESS_KEY` | 維持唯讀，一行不改 |
| AI 端改讀的憑證變數 | `S3_RW_REGION`、`S3_RW_ACCESS_KEY_ID`、`S3_RW_SECRET_ACCESS_KEY` | 僅告知 |
| 契約欄位 `clip_path` 的值 | 由本地路徑改成 `s3://aipe03-3/videos/clip_<camera>_<ts>.mp4`（**欄位名不變**）| 僅告知；`GET /events/{id}/media` 從此會回真的 presigned URL |
| 唯讀金鑰的 `GetObject` 權限 | 已用後端自己的程式碼實測 HTTP 200 | ✅ **不需要任何動作，已確認可用** |
| `event_type` 值域 | 從此恆為 `"fall"`（`chair_slip` 不再出現，型別仍是字串）| 僅告知 |
| 後端 log 的 422 毒訊息 | `agitation` / `bed_exit` / `wandering` 事件源已刪，不再進 Kafka | 僅告知，會自然消失 |

**兩組金鑰刻意分開＝最小權限**：AI 端上傳片段要 `PutObject`，後端簽 presigned URL 只要
`GetObject`。不要把讀寫金鑰塞進後端那三個名字。

### 已知殘留

- 慢車道（`nursing-home-alerts`）的事件要 `ai/vlm_worker.py` 在跑才會轉進後端。
  驗證當下 vlm_worker 沒開，所以那筆事件停在 Kafka、沒進 DB —— 這是既有行為、不是這次的迴歸。
- 片段每個 worker 生命週期只錄一次（掛在 `vlm_triggered` 一次性閂鎖下），要等第 5 項的
  冷卻計時器才會解開。

---

## 2.【已完成】六大防線收斂為「跌倒 + 巡檢」，並立了 `ai/modules/` 白名單

### 決定

`ai/modules/` **只保留 `__init__.py` 與 `sanity_check.py`**，其餘不使用也不套用。
刪除五個模組：`bed_exit.py`（A 離床）、`wandering.py`（E 遊走）、`micro_motion.py`（F 躁動）、
`audio_fusion.py`（H 音訊融合）、`chair_slip.py`（I 座椅滑落）。

### 這一刀同時解掉了舊版第 3 項的「契約破口」

舊版列的三個「自組 payload 被後端 422 丟棄」的破口（`micro_motion` / `wandering` /
`bed_exit`）**是從根拔除，不是逐一修補**——製造破口的程式碼整個不在了。

`sanity_check.py` 走的是 `nursing-home-alerts`，會先經 `vlm_worker` 重新組包成 7 欄外發，
所以它多帶的 `alert_id` / `camera_id` / `severity` / `status` 到不了後端，**不會 422**。
`severity: "low"` 是後端 2026-07-19 移除該欄位後的殘留，無害，故不修（它是白名單檔，
維持一行不動）。

### 跌倒偵測沒有被削弱

跌倒主邏輯一直都在 `ai/inference_test.py` 的 `camera_worker` 主迴圈（防線 A 肩髖體角 +
長寬比、防線 B 幾何遮擋、AcT 30 幀時序分類），**從來就不在 `modules/` 底下**。

反而是**移除了一個誤報來源**：`audio_fusion.py` 對 camera_id 含 `"303"` 的相機
**每 22 秒隨機**丟出 `THUD_CRASH`/`HELP_SCREAM`，並把信心強制拉到 `0.96` 直入快速道。
那是展示用的假資料產生器，不是偵測能力。

### 三個行為變更（要記得）

1. **`event_type` 從此恆為 `"fall"`**，`"chair_slip"` 不再出現。後端與 agent 都當字串
   處理（非 enum），不會 422。`agent/schemas.py` 的格式說明註解已同步更新。
   **payload 欄位一個字沒動**，護欄 AST 契約檢查全綠。
2. **快速道條件簡化**為 `act_confidence >= 0.90 且非遮擋`（原本多一個「或明確 chair_slip」）。
3. **巡檢間隔從 15 秒改成 60 秒**。原本 `sanity_check` 靠
   `not is_leaving_bed and not is_wandering` 兩個旗標抑制，那兩個模組刪掉後旗標恆為 False，
   等於少了兩道閘門；而 `uncertainty_router` 是「一律二審不加 discard」、`vlm_worker`
   每筆二審完成都外發，維持 15 秒的話後端會每 15 秒多一筆巡檢事件。
   間隔可用 `SANITY_INTERVAL_SEC` 調（未設＝60），**改的是呼叫端，`sanity_check.py` 沒動**。

### 規則落地：文件 + 機器都擋

- **根目錄新增 [`CLAUDE.md`](CLAUDE.md)** —— 每次動工前必讀，寫明白名單、理由、
  跌倒主邏輯在哪、以及「真的要復活」的流程。
- **[`CONTRIBUTING.md`](CONTRIBUTING.md) 第六節**加一條紅線，與 Kafka topic、
  `route_by_confidence()` payload 並列。
- **[`scripts/check_guardrails.py`](scripts/check_guardrails.py) 加 `check_module_whitelist()`**
  —— AST 靜態解析，擋兩種違規：在 `ai/modules/` 新增非白名單檔案、任何 `.py` import
  非白名單模組。pre-commit 與 GitHub Actions 兩層都會紅燈。

  為什麼一定要機器擋：這種「模組自己送 Kafka」的破口靠 code review 抓不到——它跑得動、
  不噴錯，只是訊息在後端被靜默丟掉，要跑夠長的影片才會曝露（舊版用 7~9 秒的
  test1/2/3 測了很久都沒發現，換 4.9 分鐘的 test4.mp4 才炸出來）。

  兩種違規都已用負向測試確認**擋得下來**。

### 真的要復活某個模組時

三件事缺一不可，不要只改護欄讓它過：改 `CLAUDE.md` 白名單並寫清楚為什麼收回這個決定 →
改 `scripts/check_guardrails.py` 的 `MODULES_ALLOW` → **先補契約測試**，確認該模組
不自組 payload 外發，外發一律回主迴圈的 `route_by_confidence()`。

---

## 3.【已完成】Triton GPU vs CPU 同機對照

完整報告：**[`ai/BENCHMARK_GPU_VS_CPU.md`](ai/BENCHMARK_GPU_VS_CPU.md)**。摘要：

| | GPU | CPU | 倍數 |
|---|---:|---:|---:|
| 端到端 processed FPS（單路）| **10.8 fps** | **3.2 fps** | 3.4× |
| `yolo_pose`（ONNX 兩邊同款）| 22.5 ms | 76.1 ms | 3.4× |
| `rt_detr`（GPU TensorRT vs CPU ONNX）| 17.3 ms | 192.0 ms | 11.1× |
| `action_transformer` | 2.08 ms | **0.78 ms** | **0.4×（CPU 較快）** |

三個值得記住的結論：

1. **瓶頸是 `rt_detr` 不是 pose**。CPU 上單次 192 ms，占端到端每幀時間的絕大部分。
2. **`action_transformer` 在 CPU 上比 GPU 快**——模型只有 315 KB，GPU 的 kernel 啟動與
   PCIe 搬運比算它本身還貴。之後要做混合部署的話，這顆放 CPU 是划算的。
3. **TensorRT 是真的有用**：同在 GPU 上，`rt_detr` 用 TensorRT plan 比用 ONNX 快 1.7 倍。

**新工具**（都走環境變數，未設時行為與改動前位元級相同）：
- `ai/run_triton.sh` 新增 `TRITON_GPUS`（設 `none` 就不帶 `--gpus`）、`TRITON_CPUS`
  （`--cpuset-cpus`）、`LOAD_MODELS`（原本硬編三顆模型名）
- `ai/make_cpu_repo.sh` —— 產生 CPU 版 model repository（config 改 `KIND_CPU`、
  權重用 hardlink 零額外空間）
- `ai/bench_triton.py` —— 復用線上的三支 Triton client 量測，同時抓 Triton `/metrics`
  分離出 server 端純推論時間

**下一步的明顯空間**（本輪沒做）：四顆 config 全是 `max_batch_size: 0` + `count: 1`，
等於 **dynamic batching 與多 instance 兩項都沒開**。要上多路相機，這是優先於任何
模型替換的事。

---

## 4.【只出設計】Prometheus 導入

### 對「照架構圖五個底色各包一顆 Docker」的評估：**分層很好用，但不能拿來當容器邊界**

四個具體會出錯的地方：

1. **綠色（儲存與資料服務）根本沒有 process 可以包**。PostgreSQL 是 AWS RDS、S3 是真 AWS、
   模型儲存庫也在 S3。這一層只能用 exporter 從外面看，「包一顆 docker」不成立。
2. **藍色（邊緣／運算層）內部生命週期差太多**。Triton 是常駐 GPU 服務、已經是官方容器且
   自帶 `:8002/metrics`；AI worker 是每台相機一條 thread 的 Python 行程，改邏輯就要重啟。
   綁成一顆等於「改推論程式要重啟 Triton」，會破壞已經打通的模型熱載
   （`model_control_mode=explicit` + `POST /v2/repository/models/*/load`）。至少切成兩顆。
3. **黃色（事件匯流）跟藍色裡的「訊息發佈 Kafka」是同一個 broker**。圖上兩個 Kafka 是
   兩條資料流不是兩套 broker，現況 `docker-compose.yml` 就只有一個 `nh-kafka`。
   照底色打包會做出兩個 broker。
4. **橘色把線上與離線混在一起**。「事件處理（uncertainty_router / vlm_worker，線上要低延遲）」
   跟「MLOps 迴路（Label Studio / ClearML 重訓，離線吃 GPU 很久）」同色。包成一顆的話，
   重訓一跑就排擠二審延遲。

### 建議：底色 → Prometheus label 與 Grafana 分頁，不 → 容器邊界

容器邊界照「行程生命週期 + 資源型態」切，每個 job 打上
`layer="edge|event|app|storage|mlops|control"`。分層在監控畫面上完整呈現，部署不被綁死。

可落地順序（由現成到要動工）：

| target | 端點 | 現況 | layer |
|---|---|---|---|
| Triton | `:8002/metrics` | **已經開著，零成本，最先接**（`bench_triton.py` 已經在讀它）| edge |
| backend FastAPI | `/metrics` | 要加 `prometheus-fastapi-instrumentator`；`gcp_vm_environment/test_sample/test_prometheus_fastapi.py` 有現成範例 | app |
| Kafka | JMX exporter `:5556` | `gcp_vm_environment/` 已有 jar 與 `jmx_prometheus_kafka.yml`，掛 javaagent 進 `nh-kafka` 即可 | event |
| AI worker | 自建 `prometheus_client.start_http_server` | 目前只 print（`inference_test.py` 的 FPS log），要改成 Gauge(fps) / Counter(事件數) / Histogram(各段延遲)| edge |
| GPU | dcgm-exporter | Triton metrics 已含 GPU 使用率/記憶體，要溫度功率才需要 | edge |
| RDS / S3 | CloudWatch exporter | 外部託管，無容器 | storage |

**動手前要先講清楚的一件事**：`gcp_vm_environment/` 那套已經有 Prometheus + JMX exporter +
FastAPI instrumentator，但它跟主 stack 是**兩套不同架構**（nginx + 空殼 python 容器 +
rsync 部署）。導入時是「把零件搬進主 `docker-compose.yml`」，不是兩套並存，
否則會養出第三套環境。

---

## 5.【本輪不執行】跌倒事件只發一次：改成冷卻幾分鐘後可再發

**現況**：`ai/inference_test.py` 的 `vlm_triggered` 是 per-worker 的一次性旗標。
同一路相機的 worker，**整個行程生命週期只會發出一次跌倒事件**；`ever_detected_fall`
也會讓畫面永遠停在 "FALL DETECTED!"。**片段錄製掛在同一個閂鎖下**，所以也只錄一支。

**為什麼以前沒事**：影片檔 worker 播完就結束。接上真攝影機後 worker 會跑好幾天——
等於第一次跌倒之後，那台相機就再也不會示警了。

**為什麼這輪不做**：卡在多人追蹤缺口——系統分不出同一人或另一人，加冷卻會永久漏接
冷卻期間發生的**別人**的跌倒。需要多人追蹤才能真正解決，範圍不小。

**真的要做時要想清楚的**：
- 冷卻長度用環境變數調，未設給保守預設。
- 冷卻粒度：每台相機一個，還是每種事件類型一個。
- 斷線重連時**不要**重設冷卻（現在重連刻意保留 `ever_detected_fall` / `vlm_triggered`，
  就是為了避免網路抖動導致同一起事件重複發報）。
- 不能動 `route_by_confidence()` 的 payload 欄位（護欄 AST 檢查監看）。
- 冷卻放行後，片段錄製要跟著能再錄一次（同一段程式碼，一起做比較省事）。

---

## 6.【已完成】agent P2：後端記錄 AI 判斷 + 前端顯示建議

分支 `feat/agent-p2-ai-verdict`，PR #14，已合併進 `test/main-integration`
（merge commit `23eeec9`，commits `cf2e973` + `441c0d1`）。

### 範圍（照原計畫拍板：只做 P2 的「A 層」，沒做 cutover）

- **沒有**停掉現行 `uncertainty_router.py`／`vlm_worker.py`，agent 仍是 shadow
  （`AGENT_SHADOW=1` 沒動），現行資料流沒變。
- 只做了「後端記錄 + 前端顯示」，AI 判斷是人工複判的**參考資訊**，不接手決策權。

### 做了什麼

| 任務 | 內容 |
|---|---|
| 後端欄位 | `DetectEvent`（`backend/core/models.py`）加 `ai_verdict`／`ai_confidence`／`ai_reasoning`，皆 optional，獨立於人工 `verdict`；`EventCreateRequest`、`serialize_event` 同步加 |
| DB 遷移 | 正式 RDS 已有既有資料（`create_all` 不會回頭補欄位），`core/database.py` 加回 `run_column_migrations()`（`ALTER TABLE ADD COLUMN IF NOT EXISTS`），`main.py`／`init_db.py` 都會呼叫 |
| 後端護欄 | 確認 `PATCH /events/{id}/verdict` 完全不碰 `ai_*` 欄位，沒有任何自動關閉事件的路徑；`false_alarm` 只存建議，關閉事件仍要人工按「確認誤報」 |
| 前端顯示 | 新增 `AiSuggestionBadge` 元件；**事件中心列表**（`EventCenterUnresolved.tsx`）與**詳情頁**都顯示徽章 + `ai_reasoning`；`ai_verdict=false_alarm` 時附「確認誤報」一鍵鈕，走既有 verdict 端點 |
| 測試 | 後端補 `true_alarm`／`false_alarm`／`null` 三路徑 + 舊格式相容測試，149 個 pytest 全過 |

### 實測驗證（不是推論）

拉一組拋棄式 Postgres + 這個分支的程式碼，完整模擬「正式 RDS 現況」跑過一次
migration，確認 `ALTER TABLE` 語法在真正的 PostgreSQL 上沒問題；再用 Playwright
實際開瀏覽器登入、確認事件中心列表與詳情頁的徽章、按鈕、點擊後的狀態轉換都正確。
全程沒有觸碰正在服務中的 `nh-backend`／`nh-frontend` 與正式資料庫。

也用真實 Ollama VLM 對 `ai/snapshots/` 裡的真實截圖跑過多輪判讀，把結果送進拋棄式
後端驗證整條「VLM 判斷 → 存 DB → 前端顯示」的資料管線，不是塞假資料裝樣子。

### 過程中額外修的問題：VLM 隨機拒答

驗證時發現 `llava:latest` 對**同一張圖、同一個 prompt**，在預設溫度下有機率隨機
回「無法看到圖片」之類的拒答（甚至答錯語言，測到一次葡萄牙文），技術上呼叫成功、
內容非空，但語意上等於沒判讀，且不會觸發原本的重試機制。已修：

- `agent/config.py` 新增 `vlm_temperature`（`AGENT_VLM_TEMPERATURE`，預設 `0.1`）
- `agent/nodes/vlm.py` 呼叫時帶入溫度；新增拒答關鍵字偵測，命中就當 `VlmError`
  觸發既有重試政策
- agent 全部 181 個 pytest 通過

**這個修復解決的是「模型隨機罷工」，不是「姿態判讀準不準」**——後者本來就不是
VLM 該扛的責任：`agent/nodes/vlm.py` 的既有註解就寫明「單張靜態畫面分不出躺著
休息與跌倒，時序才是關鍵」，真正的姿態判斷是防線 A（`yolo_pose` 幾何計算肩髖
體角）+ AcT 時序分類；VLM 二審只負責抓明顯誤判線索（沒人／物品掉落），設計上
就不指望它精準判讀姿態細節。用系統正式 prompt 重測同一張圖，即使套用溫度+拒答
修復，姿態描述仍會前後矛盾，證實這是模型能力上限，不是可調參數解決的。

### 已知殘留

- VLM 目前測試都只餵單張靜態截圖；`agent/nodes/vlm.py` 其實已支援多張連續畫面
  輸入（`image_paths`），理論上能顯著改善姿態判讀準確度，但這次沒有實際驗證
  多圖模式的效果，留給後續。
- `ai/snapshots/` 目錄裡有大量重複／來源不明的圖片（用 md5 比對 47 個檔案只有
  14 種真正不同內容，部分內容明顯不是這系統自己相機拍的）。不影響功能，但之後
  要挑「乾淨」的展示或測試用截圖時，這個目錄不能照單全收，要先看過內容再選。
- agent 真正即時串接寫進 DB（而非只寫 `ai/agent_shadow.jsonl` shadow log）
  是另一個小任務，這輪只驗證了「手動把 shadow 產出的判斷塞進資料庫、前端正確
  顯示」這條路徑。

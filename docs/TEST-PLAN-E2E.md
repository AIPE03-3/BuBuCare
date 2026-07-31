# 端到端測試計劃（2026-07-31）

一支新影片跑完整條鏈：串流 → 推論 → 事件 → 二審 → 資料庫 → 前端 → MLOps。
**邊跑邊填**，每個階段有通過條件；階段 1 沒過就不要往下走，後面全部依賴它。

## 測試素材

|      |                                                                       |
| ---- | --------------------------------------------------------------------- |
| 檔案 | `ai/test_demo/test_e2e_20260731.mp4`                                |
| 規格 | 1920×1080、15.03 fps、429 幀、**28.6 秒**                      |
| 版控 | **不進**（`.gitignore` 的 `*.mp4`，白名單只放行 test1/2/3） |

**影片內容人工標記**（跑階段 1 之前先看一遍填掉，這是所有延遲數字的基準）：

| # | 事件 | 影片內時間 | 備註（遮擋？幾人？） |
| - | ---- | ---------: | -------------------- |
| 1 | 跌倒 |       29秒 | 2人                  |
| 2 |      |            |                      |
| 3 |      |            |                      |

> ⚠️ **兩個時間窗要檢查**：事件片段是前 5 秒 + 後 5 秒（`CLIP_PRE_SEC` / `CLIP_POST_SEC`），
> 所以跌倒要落在 **t=5s ～ t=23.6s** 之間才錄得完整。
>
> ⚠️ **要測到 VLM／LangGraph，影片裡必須有「被遮擋的跌倒」**。分流條件是
> `is_fast_track = act_confidence >= 0.90 and not is_occluded_fall`
> （[`ai/inference_test.py:111`](../ai/inference_test.py#L111)），而 `FAST_TRACK_CONF`
> 是**寫死的常數、不吃環境變數**。乾淨的高信心跌倒會直入快速道，二審完全不會被觸發。
> 遮擋（防線 B：框高 < 參考身高 × 0.70 且框底在畫面下半）**強制走慢速道、不看信心**，
> 是唯一不改程式就能穩定觸發二審的路。

---

## 階段 0：前置健檢與回歸

**目的**：確認起點是乾淨的。跳過這關，後面每個失敗的症狀都會指向錯的方向。

```bash
# 回歸（確認這次改動沒弄壞既有的）
python3 scripts/check_guardrails.py
cd backend && SKIP_DB_INIT=1 PYTHONPATH=. ../.venv/bin/python -m pytest -q; cd ..
cd frontend && npm run build && npx eslint src --max-warnings=0; cd ..

# 服務
docker ps --format 'table {{.Names}}\t{{.Status}}'
curl -s localhost:8010/v2/health/ready -o /dev/null -w "triton ready %{http_code}\n"
for m in yolo_pose rt_detr action_transformer; do
  curl -s localhost:8010/v2/models/$m/ready -o /dev/null -w "$m %{http_code}\n"; done
curl -s localhost:8000/docs -o /dev/null -w "backend %{http_code}\n"
curl -s localhost:11434/api/tags -o /dev/null -w "ollama %{http_code}\n"

# 設定
grep -c EVENT_API_KEY .env && cat frontend/.env.local
```

| 檢查                                                        | 通過條件   | 結果 |
| ----------------------------------------------------------- | ---------- | ---- |
| 護欄                                                        | 通過       | ☐   |
| 後端 pytest                                                 | 191 passed | ☐   |
| 前端 build + ESLint                                         | 皆過       | ☐   |
| Triton 三顆模型                                             | 都`200`  | ☐   |
| 後端 / Ollama                                               | `200`    | ☐   |
| device 301 存在且`status=active`、`stream_channel` 非空 | —         | ☐   |
| `.env` 有 `EVENT_API_KEY`、`frontend/.env.local` 存在 | —         | ☐   |

> device 301：階段 1 用 `SINGLE_SOURCE`，相機名固定 `Room_301_Bed` → `device_id=301`。
> 後端沒這台裝置，`POST /events` 會回 400「裝置不存在」。

---

## 階段 1：純推論離線驗證 —— 【項目 2】影像辨識與計時

**目的**：最快拿到「抓不抓得到、要多久」。先不接前端、不接二審。

```bash
HEADLESS=1 SINGLE_SOURCE=ai/test_demo/test_e2e_20260731.mp4 DETR_EVERY_N=5 \
  ai/.venv/bin/python -u ai/inference_test.py 2>&1 | tee /tmp/stage1.log
```

**記錄表**：

| 指標                                                 | 目標                         | 實測 |
| ---------------------------------------------------- | ---------------------------- | ---- |
| 抓到幾次跌倒                                         | = 人工標記數                 |      |
| **偵測延遲**（log「已外發」− 影片內跌倒時刻） | 越小越好                     |      |
| 漏報數                                               | 0                            |      |
| 誤報數（正常走動被報）                               | 0                            |      |
| 分流落點                                             | 至少一筆走慢速道             |      |
| 逐人分案                                             | log 有「第 N 位（track M）」 |      |
| 處理 FPS                                             | —                           |      |

**通過條件**：

- ☐ 至少抓到一次跌倒
- ☐ **至少一次落在慢速道**（log 印 `VLM Queued`）—— 沒有的話遮擋段沒做出效果，
  階段 4 會測不到，要換影片或補拍

> `FALL_CONSECUTIVE_FRAMES=4`，而且每 2 幀取 1 處理。這支影片 15fps → 處理約 7.5fps
> → 需要**躺地約 0.53 秒**才判定成立。倒下瞬間一閃而過不會報，這是設計不是 bug。

---

## 階段 2：串流與前端畫面 —— 【項目 1】

⚠️ **不能用 `SINGLE_SOURCE`**：前端播的是 MediaMTX 的 `cam_in`，推論若直接讀 mp4 檔，
兩邊時間軸不同步，**骨架會對不上畫面**。兩邊必須吃同一條流。

```bash
# 終端 1：推 mp4 進 cam_in
# ⚠️ 這台 PATH 上沒有 ffmpeg，用 ai/.venv 裡 imageio-ffmpeg 附的靜態版（路徑帶版號，現查）
FF=$(ai/.venv/bin/python -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")
"$FF" -nostdin -re -stream_loop -1 -i ai/test_demo/test_e2e_20260731.mp4 \
  -an -c:v libx264 -preset ultrafast -tune zerolatency -g 30 \
  -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam_in

# ⚠️ `-rtsp_transport tcp` 不能省。MediaMTX 的 RTP/RTCP 走 UDP :8000/:8001，而
#    容器只發佈了 8554/8889/9997/8189 —— 走預設的 UDP 傳輸時媒體封包進不到容器裡，
#    MediaMTX 會在 10 秒後以 `session timed out` 踢掉推流端，ffmpeg 收到 Broken pipe。
#    症狀很誤導：paths/list 先看到 ready=True，10 秒後才變 False。

# 確認頻道有畫面（認 ready，不要看 WHEP 狀態碼）
curl -s localhost:9997/v3/paths/list | python3 -m json.tool | grep -A3 cam_in

# 終端 2：推論走 backend 拿相機清單，開座標轉播
HEADLESS=1 DETECT_BROADCAST=1 ai/.venv/bin/python -u ai/inference_test.py
```

| 檢查                                                                | 結果 |
| ------------------------------------------------------------------- | ---- |
| 監控頁畫面順暢、不卡頓                                              | ☐   |
| 切「偵測」→ 骨架與框出現                                           | ☐   |
| **切換時影像不黑一下**（新做法不重新協商 WebRTC）             | ☐   |
| 骨架**對齊人體**（畫歪＝座標正規化有問題）                    | ☐   |
| 跌倒時框變紅（`--danger`）、平時綠（`--success`）               | ☐   |
| 人離開畫面後 1.2 秒內骨架消失（`STALE_MS`，沒消失＝殘影）         | ☐   |
| 切回「即時」骨架消失                                                | ☐   |
| 拉動視窗大小，骨架跟著縮放不偏移                                    | ☐   |
| `curl -X POST localhost:8000/streams/detections` 回 **401** | ☐   |

---

## 階段 3：事件鏈 —— 【項目 4、5】資料庫與前端推送

```bash
ai/.venv/bin/python -u ai/monitor_kafka.py    # 終端 3：看 processed-reports
docker logs -f nh-backend                      # 終端 4
```

**時間鏈**（四個錨點，逐段算差）：

| 錨點                          | 來源                       | 時刻 |
| ----------------------------- | -------------------------- | ---- |
| t0 影片內跌倒                 | 人工標記                   |      |
| t1 inference「已外發」        | 推論 log                   |      |
| t2 Kafka`processed-reports` | `monitor_kafka.py`       |      |
| t3 後端`POST /events 201`   | `docker logs nh-backend` |      |
| t4 前端事件卡／全螢幕警示     | 碼錶                       |      |

| 檢查                                                                                                                                     | 結果 |
| ---------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| 後端回**201**，不是 422（422＝payload 欄位對不上契約）                                                                             | ☐   |
| DB 真的有這筆（`select event_id, device_id, event_type, detected_at, clip_path from detect_event order by detected_at desc limit 5;`） | ☐   |
| `clip_path` 是 `s3://` 開頭                                                                                                          | ☐   |
| 前端全螢幕警示跳出                                                                                                                       | ☐   |
| 可「接手」→ 狀態變`in_progress`                                                                                                       | ☐   |
| 可「標記誤報」→`verdict=false_alarm`                                                                                                  | ☐   |
| 事件中心列表出現該筆                                                                                                                     | ☐   |

---

## 階段 4：VLM 與 LangGraph 複判 —— 【項目 3】

⚠️ **慢速道有兩個消費者併行**，group_id 刻意不同
（[`agent/config.py:108`](../agent/config.py#L108)）：

| 消費者                         | group_id              | 預設                                                      |
| ------------------------------ | --------------------- | --------------------------------------------------------- |
| `ai/vlm_worker.py`           | `vlm-brain-cluster` | —                                                        |
| `agent/main.py`（LangGraph） | `agent-reviewer`    | `AGENT_SHADOW=0`＝**非 shadow，會真的送 Kafka 2** |

> **同一則低信心事件可能產生兩筆 `processed-reports` → DB 兩筆重複事件。
> 這件事尚未驗證過，是本階段要確認的第一件事。**

**分兩輪跑**才分得清是誰的效果：

```bash
# 輪 A：只開 vlm_worker
# ⚠️ 順序不能反：它是 auto_offset_reset='latest'，先跑推論它會看不到事件
cd ai && VLM_MODEL_NAME=qwen2.5vl:7b ../.venv/bin/python -u vlm_worker.py

# 輪 B：只開 agent，先用 shadow（判定只寫 log 不送 Kafka，不污染 DB）
AGENT_SHADOW=1 .venv/bin/python -u -m agent.main
# 判定記錄：agent_shadow.jsonl
```

| 指標                         | 實測 |
| ---------------------------- | ---- |
| VLM 二審耗時（收到 → 送出） |      |
| agent 耗時                   |      |
| 兩者判斷是否一致             |      |
| 是否產生重複事件             |      |

**判斷品質**（逐筆人工比對，填混淆矩陣）：

|                   | 實際跌倒 | 實際沒跌倒 |
| ----------------- | -------: | ---------: |
| 判`true_alarm`  |          |            |
| 判`false_alarm` |          |            |

| 檢查                                                                        | 結果 |
| --------------------------------------------------------------------------- | ---- |
| `vlm_summary` 文字合理、無幻覺                                            | ☐   |
| 前端全螢幕警示出現**「AI 影像分析判斷理由」區塊**（需`vlm_summary` 非空） | ☐   |

---

## 階段 5：片段與快照回放

demo 最容易出糗的地方，而且讀寫是**兩組不同金鑰**（見 `CLAUDE.md` 第三節），
很容易只驗到寫、沒驗到讀。

| 檢查                                                           | 結果 |
| -------------------------------------------------------------- | ---- |
| 前端點事件 → 影片播得出來（presigned URL，唯讀金鑰）          | ☐   |
| 片段**真的涵蓋跌倒瞬間**（前 5 秒 + 後 5 秒）            | ☐   |
| 快照圖看得到人                                                 | ☐   |
| 片段是 H.264，Safari 也播得動                                  | ☐   |
| 片段是**無框的原始畫面**（組長決策：有框會干擾人工確認） | ☐   |

---

## 階段 6：MLOps —— 【項目 6】Label Studio 與 ClearML

⚠️ **兩個前置限制**：

1. 本機 `ai/active_learning_dataset/` **只有 14 張圖**，重訓結果沒有統計意義
   —— 這階段驗的是「管線通不通」，不是模型好不好
2. **YOLO-Pose 那條完全沒有資料**（標註全是 5 欄偵測格式），要測得先開骨架
   Label Studio 專案（`LS_POSE_PROJECT_ID`）標一批。見 [`../ai/MLOPS.md`](../ai/MLOPS.md) 第二節

```bash
python ai/inference_to_labelstudio_sdk.py       # 偵測那條的標註同步
python ai/pose_to_labelstudio_sdk.py --check    # 骨架那條先對帳

TRIGGER_THRESHOLD=3 python ai/webhook_receiver.py   # 自動點火（門檻改小，別改預設值）

python ai/prepare_dataset.py --dry-run          # 先看統計不寫檔
python ai/prepare_dataset.py
TRAIN_EPOCHS=3 python ai/submit_task.py         # sanity 用小 epoch

python ai/model_deployment_agent.py             # 熱部署（訓完 ≠ 上線）
python ai/model_deployment_agent.py --rollback  # 回滾也要測
```

| 檢查                                                   | 結果 |
| ------------------------------------------------------ | ---- |
| 標註推得進 Label Studio、拉得回本地                    | ☐   |
| 平衡抽樣的分組統計合理                                 | ☐   |
| 累積到門檻會自動點火                                   | ☐   |
| mAP 沒過門檻時標`below-gate` 而非 `best`（防退步） | ☐   |
| 熱部署後 Triton 版本號有變、推論還能跑                 | ☐   |
| 回滾能還原                                             | ☐   |

---

## 階段 7：降級與壓力（可選，但上線前要做）

| 檢查                                         | 做法                       | 結果 |
| -------------------------------------------- | -------------------------- | ---- |
| Triton 掛掉 → 推論降級不整支死              | `docker stop nh-triton`  | ☐   |
| Kafka 掛掉 → 事件不外發但推論續跑           | `docker stop nh-kafka`   | ☐   |
| 後端掛掉 → 座標轉播印一次警告後退避，不洗版 | `docker stop nh-backend` | ☐   |
| 多路併發 FPS                                 | `STRESS_CAM_COUNT=4`     | ☐   |
| 資源占用                                     | CPU / 記憶體               | ☐   |

---

## 執行紀錄

| 階段        | 日期       | 結果                             | 備註                                                                                                                                 |
| ----------- | ---------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| 0 前置健檢  | 2026-07-31 | **離線部分全過，服務未起** | 護欄✅／pytest 191✅／前端 build+ESLint✅／`.env` 與 `frontend/.env.local` 齊✅。Docker Desktop 與 Ollama 未啟動，服務類檢查待補 |
| 1 純推論    |            |                                  |                                                                                                                                      |
| 2 串流前端  |            |                                  |                                                                                                                                      |
| 3 事件鏈    |            |                                  |                                                                                                                                      |
| 4 VLM/agent |            |                                  |                                                                                                                                      |
| 5 回放      |            |                                  |                                                                                                                                      |
| 6 MLOps     |            |                                  |                                                                                                                                      |
| 7 降級壓力  |            |                                  |                                                                                                                                      |

# MLOps 迴路 —— 標註 → 重訓 → 熱部署

這條迴路讓模型能持續進步：現場拍到的畫面進標註平台、人工確認、累積到量自動重訓、
訓出更好的模型自動換上線。日常開發**不需要**起這裡的服務；只有要重訓模型時才用。

```
邊緣端快照 ai/active_learning_dataset/
        │
        v
  Label Studio (8082) ── AI 預標註 ──> 人工審核 Submit
        │                                    │ webhook
        │                                    v
        │                        ai/webhook_receiver.py (9001)
        │                                    │ 累積到門檻
        │                                    v
        │                          ai/submit_task.py ──> ClearML 佇列 (8008)
        │                                                      │
        │                                              clearml-agent 咬單
        │                                                      v
        └──> ai/prepare_dataset.py ──> ai/clearml_train_pipeline.py
                （清洗 + 切 train/val）      訓練 → 評估 mAP → 上傳 S3 標 best
                                                              │
                                              ai/model_deployment_agent.py
                                                              v
                                          .pt → ONNX → TensorRT → Triton 熱切版
```

## 一、各支腳本

| 檔案 | 做什麼 |
|---|---|
| [`export_models.py`](export_models.py) | 從 `.pt`/`.pth` 重建 `triton_repo/` 的三顆模型（含 TensorRT 引擎）|
| [`prepare_dataset.py`](prepare_dataset.py) | 清洗標註、切 train/val |
| [`inference_to_labelstudio_sdk.py`](inference_to_labelstudio_sdk.py) | Label Studio 雙向同步（推 AI 預標註 / 拉人工標註）|
| [`webhook_receiver.py`](webhook_receiver.py) | 收 Label Studio webhook，累積到門檻就點火 |
| [`submit_task.py`](submit_task.py) | 把重訓任務排進 ClearML 佇列 |
| [`clearml_train_pipeline.py`](clearml_train_pipeline.py) | 實際的訓練、評估、上傳（由 clearml-agent 執行）|
| [`model_deployment_agent.py`](model_deployment_agent.py) | 把新模型熱部署進 Triton，可回滾 |
| [`mlops_paths.py`](mlops_paths.py) | 共用路徑與設定取值 |

設定一律走 `mlops_paths.cfg()`（真實環境變數優先於 **repo 根目錄**的 `.env`），
與 `ai/inference_test.py` 同一套規則。不要讀 `ai/.env`（見 [`../CLAUDE.md`](../CLAUDE.md) 第四節）。

## 二、跑一次完整迴路

### 0. 前置

```bash
cp ai/clearml.conf.example ~/clearml.conf     # 填入 credentials（見該檔說明）
```

根目錄 `.env` 需要（`.env` 已在 `.gitignore`）：

```
LS_URL=http://localhost:8082
LS_PROJECT_ID=1
LABEL_STUDIO_USERNAME=...
LABEL_STUDIO_PASSWORD=...
```

### 1. 起服務

```bash
docker compose -p ai -f ai/docker-compose-clearml.yml up -d
docker compose -p ai -f ai/docker-compose-labelstudio.yml up -d
```

⚠️ **`-p ai` 不能省** —— compose 專案名決定 volume 名稱，換了就接不上既有的
`ai_clearml-*` / `ai_lsdata`，等於開一套空的、既有實驗與標註全看不到。

檢查：`curl localhost:8008/debug.ping`（api）、`localhost:8085`（web）、
`localhost:8081`（files）、`localhost:8082`（Label Studio）。

### 2. 標註

```bash
python ai/inference_to_labelstudio_sdk.py     # 沒標註的跑 AI 預標註、已標註的拉回本地
```

人到 http://localhost:8082 審核、修正、Submit。

### 3. 自動點火（可選；也可以直接跳到第 4 步手動排單）

```bash
python ai/webhook_receiver.py                 # 監聽 9001
# 生產門檻是 50 則標註；本機驗證整條流程用 TRIGGER_THRESHOLD=3 之類的小值
```

Label Studio 那邊要建一個 webhook 指向 `http://host.docker.internal:9001/webhook`
（`ANNOTATION_CREATED` / `ANNOTATION_UPDATED`）。容器打得到 host 是靠
`docker-compose-labelstudio.yml` 的 `extra_hosts: host.docker.internal:host-gateway`。

### 4. 清洗 + 重訓

```bash
python ai/prepare_dataset.py                  # 清洗、切 train/val

# 起 agent（沿用 ai/.venv，不讓它每次重建環境）
CLEARML_AGENT_SKIP_PIP_VENV_INSTALL="$(pwd)/ai/.venv/bin/python" \
  ai/.venv/bin/clearml-agent daemon --queue default --gpus 0

# 另一個終端排單
TRAIN_EPOCHS=100 TRAIN_BATCH=8 python ai/submit_task.py
```

進度看 http://localhost:8085。

### 5. 熱部署

```bash
python ai/model_deployment_agent.py           # 拉 ClearML 上標 best 的最新權重上線
python ai/model_deployment_agent.py --rollback   # 出事切回上一版
```

## 三、mAP 門檻與 2026-07-29 的實際數字

**門檻：`mAP50 ≥ 0.80`**（會議訂的 80~90%）。兩個地方都會擋：
`clearml_train_pipeline.py` 決定要不要標 `best`、`model_deployment_agent.py` 決定要不要部署
（`DEPLOY_MIN_MAP50`，`--force` 可覆寫）。

本輪實測（ClearML task `8d3d9421`，100 epochs / batch 8 / RTX 5060 Ti，0.155 小時）：

| 指標 | 數字 |
|---|---:|
| **mAP50** | **0.9912** |
| **mAP50-95** | **0.9851** |
| person | 0.980 |
| chair | 0.995 |
| sofa | 0.995 |
| tv | 0.995 |
| bed | —（沒有任何標註）|

### ⚠️ 這個 0.99 不能當泛化能力的證據

三個具體理由，**做結論前一定要一起看**：

1. **資料量太小且高度重複**。全部只有 111 張快照、清洗後 90 張可用，而且是同幾個房間、
   同幾支相機拍的連續畫面 —— 同一行標註內容在 22 個不同檔案裡重覆出現。
2. **80/20 隨機切分擋不住這種重複**。切出來的 18 張 val 幾乎一定有「同場景、相鄰幾秒」
   的兄弟留在 train 裡。這是「同場景不同幀」的切分，不是「沒看過的場景」的切分，
   模型等於在考已經念過的內容。要拿到有意義的數字，得**按場景/相機/日期分組切**，
   或直接換一批新場景當測試集。
3. **`bed` 這一類一個標註都沒有**，`sofa` 只有 5 個框（val 裡 2 個）。這兩類的數字
   不具統計意義。

**結論**：這個數字證明的是「重訓管線是通的、模型確實學到了這批資料」，
**不是**「模型在新病房也有 99% 的準確率」。要回答後者，先補資料與分組切分。

## 四、資料清洗擋掉了什麼（2026-07-29 實跑）

```
標註行  保留 362 / 丟棄 41（寫死的假 pose 行 21、中文註解行 20）
圖片    來源 111 -> 可用 90，隔離 21（清完 0 個框）
切分    train 72 / val 18（seed=20260729）
類別    person 86 / chair 92 / sofa 5 / bed 0 / tv 179
```

那 21 個假標註是舊 `vlm_worker` 寫死的座標，17 個關節點完全相同、每張圖一模一樣、
與畫面無關。**不能照上游的做法截前 5 欄** —— 截完會變成一個看起來合理但憑空捏造的框
混進訓練集。偵測規則是「所有關節點座標相同」，理由與規則細節見
[`prepare_dataset.py`](prepare_dataset.py) 檔頭。

## 五、類別對照表：三邊必須一致

| class id | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| [`data.yaml`](data.yaml)（唯一真相）| person | chair | sofa | bed | tv |
| Label Studio 專案標籤 | person | chair | sofa | bed | tv |
| 重訓後的 `rt_detr` 輸出 | person | chair | sofa | bed | tv |

`inference_to_labelstudio_sdk.py` 啟動時會拿 Label Studio 的標註介面設定跟 `data.yaml`
對帳，對不上直接停 —— 因為類別錯位是「訓練照樣成功、完全看不出來」的錯誤。

⚠️ **不要照抄 albert 那份 `data.yaml`**（wheelchair/slipper/wire/obstacle/walker）。
那是他那邊的類別，與這台的資料對不上。判斷依據是逐類數量比對，記在
[`data.yaml`](data.yaml) 的註解裡。

## 六、踩過的坑（都是「不報錯但結果是錯的」那種）

| 坑 | 症狀 | 解 |
|---|---|---|
| 超參數用環境變數傳給 agent | 排隊端設 `TRAIN_EPOCHS=60`，agent 印 `epochs=1`。訓練照跑、零紅字 | 走 Task 參數（agent 是另一個行程，不繼承 `os.environ`）|
| `Model.created` 在 clearml 2.1.10 不存在 | 「繼承上一輪最強大腦」被 except 吞掉，每輪冷啟動，滾動重訓從沒滾動過 | 逐一嘗試 `created`/`last_update`/`published` |
| 每輪都無條件標 `best` | 1 epoch 的 sanity（mAP 0.02）排在正式那輪（0.99）前面，下一輪會去繼承它、部署端會抓它上線 | 只有過門檻才標 `best`，沒過標 `below-gate` |
| `task.get_models()["output"][-1]` | ClearML 把「拿來繼承的輸入權重」也登記成這個 task 的模型，標籤標到錯的物件上 | 挑 url 以 `best.pt` 結尾的那顆，標完讀回來對帳 |
| trtexec 覆蓋舊 `.plan` | 編譯跑完 4 分鐘之後才在存檔那刻炸 `Cannot write to FileStreamWriter` | 編譯前先 unlink，容器帶 `--user $(id -u):$(id -g)` |
| ClearML fileserver/webserver 起不來 | 手動 `docker run` 起的容器沒有上游服務名，fileserver 連 `redis:6379`、webserver nginx 找 `upstream apiserver` 全部失敗，Exited 好幾天沒人發現 | compose 加 network aliases |
| Label Studio 1.23 legacy token | `/api/projects` 回 401 `legacy token authentication has been disabled` | 走 session 登入 |

## 七、關掉服務

```bash
docker compose -p ai -f ai/docker-compose-labelstudio.yml stop
docker compose -p ai -f ai/docker-compose-clearml.yml stop
```

用 `stop` 不用 `down`：資料在 named volume 裡，`down -v` 才會刪，但沒必要冒這個險。

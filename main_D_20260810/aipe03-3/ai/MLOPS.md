# MLOps 迴路 —— 標註 → 重訓 → 熱部署

這條迴路讓模型能持續進步：現場拍到的畫面進標註平台、人工確認、累積到量自動重訓、
訓出更好的模型自動換上線。日常開發**不需要**起這裡的服務；只有要重訓模型時才用。

**有兩條線**（2026-07-31 起）：`rt_detr` 環境物件偵測、`yolo_pose` 人體骨架。
兩條吃**同一批圖片**、走同一套服務與同一套排隊機制，只在「標註成什麼格式、餵給誰訓練」
分岔——因為 RT-DETR 看不懂關節點、YOLO-Pose 沒有關節點就訓練不了。

```
邊緣端快照 ai/active_learning_dataset/images/   ← 圖片兩條線共用
        │
        v
  Label Studio (8082) ── AI 預標註 ──> 人工審核 Submit
   ├─ 專案 LS_PROJECT_ID      （框）      │ webhook
   └─ 專案 LS_POSE_PROJECT_ID（框＋17 點）│
        │                                    v
        │                        ai/webhook_receiver.py (9001)
        │                                    │ 累積到門檻
        │                                    v
        │                          ai/submit_task.py ──> ClearML 佇列 (8008)
        │                          （--task detect|pose）        │
        │                                              clearml-agent 咬單
        │                                                       v
        ├─ labels/      ─ prepare_dataset.py ────────> clearml_train_pipeline.py
        │  （偵測框）      （detection_dataset/）        RT-DETR：評估 box mAP50
        │                                                       │
        └─ pose_labels/ ─ prepare_dataset.py --task pose ─> clearml_pose_train_pipeline.py
           （骨架點）       （pose_dataset/）              YOLO-Pose：評估 pose mAP50
                                                                │
                                            過門檻 → 上傳 S3 標 best
                                                                v
                                              ai/model_deployment_agent.py
                                                                v
                                          .pt → ONNX → TensorRT → Triton 熱切版
```

## 一、各支腳本

| 檔案 | 做什麼 | 哪條線 |
|---|---|---|
| [`export_models.py`](export_models.py) | 從 `.pt`/`.pth` 重建 `triton_repo/` 的三顆模型（含 TensorRT 引擎）| 共用 |
| [`prepare_dataset.py`](prepare_dataset.py) | 清洗標註、切 train/val（`--task detect\|pose`）| 共用 |
| [`labelstudio_client.py`](labelstudio_client.py) | Label Studio 的連線與取檔管線 | 共用 |
| [`webhook_receiver.py`](webhook_receiver.py) | 收 Label Studio webhook，累積到門檻就點火 | **只點 rt_detr**（見第二節第 3 步）|
| [`submit_task.py`](submit_task.py) | 把重訓任務排進 ClearML 佇列（`--task detect\|pose`）| 共用 |
| [`model_deployment_agent.py`](model_deployment_agent.py) | 把新模型熱部署進 Triton，可回滾 | 共用 |
| [`mlops_paths.py`](mlops_paths.py) | 共用路徑與設定取值 | 共用 |
| [`inference_to_labelstudio_sdk.py`](inference_to_labelstudio_sdk.py) | LS 雙向同步（推**框**預標註 / 拉人工標註）| rt_detr |
| [`clearml_train_pipeline.py`](clearml_train_pipeline.py) | 訓練、評估 box mAP、上傳（由 clearml-agent 執行）| rt_detr |
| [`pose_to_labelstudio_sdk.py`](pose_to_labelstudio_sdk.py) | LS 雙向同步（推**框＋17 關節點** / 拉人工標註）| yolo_pose |
| [`clearml_pose_train_pipeline.py`](clearml_pose_train_pipeline.py) | 訓練、評估 pose mAP、上傳 | yolo_pose |

⚠️ **兩條線的標註各自落在不同目錄**：`active_learning_dataset/labels/`（偵測框）與
`active_learning_dataset/pose_labels/`（骨架點）。**刻意不共用**——同一張圖可能在兩個
Label Studio 專案裡都被標，兩支腳本都寫 `{stem}.txt` 的話後跑的會**靜默蓋掉**先跑的。
pose 標註（56 欄）雖然是偵測標註（5 欄）的超集，反過來不成立，被蓋掉就等於關節點全丟。

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
LS_PROJECT_ID=1            # 偵測框專案（rt_detr 那條）
LS_POSE_PROJECT_ID=2       # 骨架專案（yolo_pose 那條），只有要訓練骨架才需要
LABEL_STUDIO_USERNAME=...
LABEL_STUDIO_PASSWORD=...
# 可選：設了才會在重訓過關/未過關時發 Discord 通知。沒設就不通知。
# ⚠ 不要在程式裡留預設值——上游 albert 那份把一組可用的 webhook 寫進原始碼當
#   os.getenv 的預設值，等於機密進版控。
# DISCORD_WEBHOOK_URL=...
```

**骨架專案的標註介面**必須同時有這兩個控制項（少一個 `pose_to_labelstudio_sdk.py`
啟動就會擋下來），關節點標籤名要與 COCO 17 點逐字相同：

```xml
<View>
  <Image name="image" value="$image"/>
  <RectangleLabels name="label" toName="image">
    <Label value="person"/>
  </RectangleLabels>
  <KeyPointLabels name="kp-1" toName="image">
    <Label value="nose"/><Label value="left_eye"/><Label value="right_eye"/>
    <Label value="left_ear"/><Label value="right_ear"/>
    <Label value="left_shoulder"/><Label value="right_shoulder"/>
    <Label value="left_elbow"/><Label value="right_elbow"/>
    <Label value="left_wrist"/><Label value="right_wrist"/>
    <Label value="left_hip"/><Label value="right_hip"/>
    <Label value="left_knee"/><Label value="right_knee"/>
    <Label value="left_ankle"/><Label value="right_ankle"/>
  </KeyPointLabels>
</View>
```

⚠️ **框不能省**。YOLO-Pose 的標註是「框 + 掛在框上的關節點」，少了框湊不出訓練標籤；
而且回收時就是靠「關節點落在哪個框裡」還原「這 17 點屬於哪一個人」
（Label Studio 的 keypoint 各自獨立，不會告訴你分組）。

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

**rt_detr（偵測框）**：

```bash
python ai/inference_to_labelstudio_sdk.py     # 沒標註的跑 AI 預標註、已標註的拉回本地
```

**yolo_pose（骨架）**：

```bash
python ai/pose_to_labelstudio_sdk.py --check  # 先對帳：介面有沒有那兩個控制項、17 點名字對不對
python ai/pose_to_labelstudio_sdk.py          # 對帳過了再跑雙向同步
```

人到 http://localhost:8082 審核、修正、Submit。

兩支都是「有人工標註就拉回本地、沒有就跑推論注入 AI 預標註」，靠 task 有沒有標註自動
分流，人工結果永遠優先。推論都打**線上的 Triton**（`rt_detr` / `yolo_pose`），不另外載
本地權重——要驗的就是「線上這顆現在畫得如何」。

### 3. 自動點火（可選；也可以直接跳到第 4 步手動排單）

```bash
python ai/webhook_receiver.py                 # 監聽 9001
# 生產門檻是 50 則標註；本機驗證整條流程用 TRIGGER_THRESHOLD=3 之類的小值
```

Label Studio 那邊要建一個 webhook 指向 `http://host.docker.internal:9001/webhook`
（`ANNOTATION_CREATED` / `ANNOTATION_UPDATED`）。容器打得到 host 是靠
`docker-compose-labelstudio.yml` 的 `extra_hosts: host.docker.internal:host-gateway`。

> ⚠️ **自動點火目前只會排 rt_detr 那條。** `webhook_receiver.py` 呼叫的是
> `submit()` 的預設值（`task_kind="detect"`），而且它是**不分專案**在數標註筆數的——
> 所以**不要**把骨架專案的 webhook 也指到 9001：那會讓你標骨架、卻排出一張 RT-DETR
> 的重訓單，而且完全不報錯。骨架那條請用第 4 步的手動排單
> （`python ai/submit_task.py --task pose`）。
>
> 要讓它認得兩條線，得讓 `webhook_receiver.py` 從 webhook payload 讀 `project` id、
> 對照 `LS_PROJECT_ID` / `LS_POSE_PROJECT_ID` 決定 `task_kind`，並且兩條各自計數。
> 沒做是因為骨架那條還沒有實跑過（見第四節），先手動排單把流程走通再自動化。

### 4. 清洗 + 重訓

```bash
# 清洗、切 train/val。--dry-run 只印統計不寫檔（不會動到 dataset_splits/）
python ai/prepare_dataset.py                  # rt_detr：labels/ → detection_dataset/
python ai/prepare_dataset.py --task pose      # yolo_pose：pose_labels/ → pose_dataset/

# 起 agent（沿用 ai/.venv，不讓它每次重建環境）。兩條線共用同一個 agent 與佇列。
CLEARML_AGENT_SKIP_PIP_VENV_INSTALL="$(pwd)/ai/.venv/bin/python" \
  ai/.venv/bin/clearml-agent daemon --queue default --gpus 0

# 另一個終端排單
TRAIN_EPOCHS=100 TRAIN_BATCH=8 python ai/submit_task.py                # rt_detr
TRAIN_EPOCHS=100 python ai/submit_task.py --task pose                  # yolo_pose
```

進度看 http://localhost:8085。

**切分策略**（`--split-strategy`，預設 `balanced`）：依「最稀有類別」分組後各組各自切
80/20。本專案的類別分佈很偏（tv 179 個框、sofa 只有 5 個），純隨機切有三成機率讓稀有
類別整組落在同一邊——落在 train 就是 val 評估不到、mAP 虛高；落在 val 就是模型沒學過、
那一類必定 0 分。演算法與四處「不照上游抄」的地方見
[`prepare_dataset.py`](prepare_dataset.py) 檔頭。要重現第三節那組舊數字請加
`--split-strategy random`。

**兩條線的 device 預設不同**：rt_detr 固定 `device=0`（5060 Ti）；yolo_pose 是 `auto`
（cuda → mps → cpu），因為骨架重訓在 Mac 本機也要跑得起來。要覆寫就設 `TRAIN_DEVICE`。

### 5. 熱部署

```bash
python ai/model_deployment_agent.py           # 拉 ClearML 上標 best 的最新權重上線
python ai/model_deployment_agent.py --rollback   # 出事切回上一版
```

## 三、mAP 門檻與 2026-07-29 的實際數字（rt_detr）

**門檻：`mAP50 ≥ 0.80`**（會議訂的 80~90%）。兩個地方都會擋：
`clearml_train_pipeline.py` 決定要不要標 `best`、`model_deployment_agent.py` 決定要不要部署
（`DEPLOY_MIN_MAP50`，`--force` 可覆寫）。

**yolo_pose 那條的門檻是分開的**（環境變數 `POSE_MAP50_GATE`，預設同樣 0.80），
而且**看的是 pose mAP50 不是 box mAP50**：框畫得準但關節點全錯的模型對跌倒判定毫無用處，
而 box mAP 幾乎一定比 pose 高，拿它對門檻等於門檻形同虛設。另外骨架那條要**兩道關卡
都過**才標 `best`——過絕對門檻**且**不低於上一輪，不然滾動式重訓會一輪一輪往下掉。

模型標籤也分開：rt_detr 是 `best` / `below-gate`，yolo_pose 是
`["yolo","pose","best"]` 三個一組。兩條線共用同一個 ClearML 專案，只靠 `best` 一個標籤
會讓下一輪把 RT-DETR 的權重餵給 YOLO-Pose。

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
2. **80/20 切分擋不住這種重複**。切出來的 18 張 val 幾乎一定有「同場景、相鄰幾秒」
   的兄弟留在 train 裡。這是「同場景不同幀」的切分，不是「沒看過的場景」的切分，
   模型等於在考已經念過的內容。要拿到有意義的數字，得**按場景/相機/日期分組切**，
   或直接換一批新場景當測試集。
   > ⚠️ 2026-07-31 起預設換成平衡抽樣（見第二節第 4 步），但**這一點沒有被解決**。
   > 平衡抽樣解的是「稀有類別會整組落到同一邊」，不是「同場景不同幀」的資料洩漏——
   > 兩個是不同的問題，別把換了切分策略當成這條警告已經失效。
3. **`bed` 這一類一個標註都沒有**，`sofa` 只有 5 個框（val 裡 2 個）。這兩類的數字
   不具統計意義。

**結論**：這個數字證明的是「重訓管線是通的、模型確實學到了這批資料」，
**不是**「模型在新病房也有 99% 的準確率」。要回答後者，先補資料與分組切分。

## 四、資料清洗擋掉了什麼（2026-07-29 實跑，rt_detr）

```
標註行  保留 362 / 丟棄 41（寫死的假 pose 行 21、中文註解行 20）
圖片    來源 111 -> 可用 90，隔離 21（清完 0 個框）
切分    train 72 / val 18（seed=20260729）
類別    person 86 / chair 92 / sofa 5 / bed 0 / tv 179
```

> ⚠️ 這組切分是 **`--split-strategy random`（舊的純隨機）** 跑出來的，版控裡的
> `dataset_splits/train.txt`、`val.txt` 也是那一輪的產物。2026-07-31 起預設改成平衡
> 抽樣，重跑 `prepare_dataset.py` 會**切出不一樣的一組**——第三節那個 mAP50=0.9912
> 是對應舊切分的數字，要重現得加 `--split-strategy random`。

那 21 個假標註是舊 `vlm_worker` 寫死的座標，17 個關節點完全相同、每張圖一模一樣、
與畫面無關。**不能照上游的做法截前 5 欄** —— 截完會變成一個看起來合理但憑空捏造的框
混進訓練集。偵測規則是「所有關節點座標相同」，理由與規則細節見
[`prepare_dataset.py`](prepare_dataset.py) 檔頭。

**yolo_pose 那條的清洗多四道檢查**（`--task pose`）：關節點必須剛好 17 組、只收
class 0（person）、純 5 欄的偵測標註直接丟（沒有關節點，餵進去等於給模型一副全 0 的
骨架當答案）、關節點座標夾回 `[0,1]` 而 visibility 只認 0/1/2。

> ⚠️ **這條線目前還沒有資料可跑。** 本機 `active_learning_dataset/labels/` 全是 5 欄
> 偵測標註，`--task pose` 實跑是 144 行全丟、可用圖片 0。骨架訓練資料要靠
> `pose_to_labelstudio_sdk.py` 從骨架專案拉回來（見第二節第 2 步），這是唯一來源。

## 五、類別對照表：三邊必須一致（rt_detr）

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

**yolo_pose 是單類別任務，不吃上面那張表**：[`pose_data.yaml`](pose_data.yaml) 是
`nc: 1`（只有 person）+ `kpt_shape: [17, 3]`。chair/sofa/bed/tv 沒有骨架可言，
收進來只會讓 class id 語意錯位，所以 `--task pose` 會強制只留 class 0。

`kpt_shape` 的 17 是**三邊契約**：`prepare_dataset.py` 的 `NUM_KEYPOINTS`（清洗時檢查
每行剛好 17 組）、`inference_test.py` 的姿態特徵（34 維 = 17 點 × (x, y)）、
上線的 `yolo11s-pose` 本身。改成別的點數，重訓出來的模型會與推論端的特徵維度對不上，
Triton 的 `config.pbtxt` 輸出形狀也要跟著改。

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
| 兩條線共用 `labels/` 目錄 | 同一張圖在兩個 LS 專案都標過時，後跑的那支**靜默蓋掉**先跑的；pose 被偵測蓋掉＝關節點全丟 | 分成 `labels/` 與 `pose_labels/` 兩個目錄 |
| 兩條線共用 `best` 標籤 | 下一輪繼承時把 RT-DETR 的權重餵給 YOLO-Pose | pose 用 `["yolo","pose","best"]` 三個一組查 |
| pose 門檻誤用 box mAP50 | 框準、關節點全錯的模型照樣過關 —— 而 box mAP 幾乎一定比 pose 高，門檻形同虛設 | 門檻只看 `metrics.pose.map50` |
| Discord webhook 寫死在原始碼 | 上游把一組**可用的** token 寫成 `os.getenv` 的預設值，等於機密進版控 | 不留預設值，沒設就不通知 |

## 七、關掉服務

```bash
docker compose -p ai -f ai/docker-compose-labelstudio.yml stop
docker compose -p ai -f ai/docker-compose-clearml.yml stop
```

用 `stop` 不用 `down`：資料在 named volume 裡，`down -v` 才會刪，但沒必要冒這個險。

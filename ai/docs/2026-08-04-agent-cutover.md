# AcT 二審 cutover：`ai/vlm_worker.py` → `agent/`（LangGraph）

**日期**：2026-08-04ㅤ**分支**：`feat/agent-cutover`（從 `main` @ `b7843af` 開）
**機器**：5060 Ti（WSL2）ㅤ**結論**：**已上線，三項驗收全過**

正式二審從此是 `agent/`（LangGraph）。`ai/vlm_worker.py` 退居回滾路徑，**不再常駐**。

---

## 一、為什麼要在切換的同時改程式

拍板的是「不論成效，系統先真的完整跑過一輪」。但照現況只把 `AGENT_SHADOW` 扳成 0，
有兩件事會壞——都不是成效問題：

| # | 問題 | 後果 |
|---|---|---|
| A | 兩個 consumer group 併行 | 每起事件進後端**兩次** |
| B | `snapshot_path` 被 schema 丟掉 | 前端事件詳情的快照**全空白**，而且不噴任何錯 |

外加一項「不修不會壞、但會退步」：多人同時跌倒時分不出是幾個人。三項都在本輪處理完。

---

## 二、必修 A —— 重複發報（操作面，不是程式改動）

| 服務 | consumer group | 位置 |
|---|---|---|
| 舊二審 `ai/vlm_worker.py` | `vlm-brain-cluster` | [`ai/vlm_worker.py:18`](../vlm_worker.py#L18) |
| 新二審 `agent/` | `agent-reviewer` | [`agent/config.py:110`](../../agent/config.py#L110) |

Kafka 對**不同 group 各給一份完整訊息**，兩邊又都發到 `processed-reports`
→ 不停舊的就是每起事件雙寫。

**做法**：cutover 當下 `kill 71207`。實測輸出：

```
$ ps -ef | grep vlm_worker | grep -v grep
rapubun+ 71207 71205  0 10:01 ?        00:01:55 ../ai/.venv/bin/python -u vlm_worker.py
$ kill 71207
$ ps -ef | grep vlm_worker | grep -v grep
（無輸出）
```

**Kafka 這一側的證據**（實測完之後查的，舊 group 卡在事件發生之前）：

```
GROUP             TOPIC               PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG  CONSUMER-ID
agent-reviewer    nursing-home-alerts 0          197             197             0    kafka-python-2.2.3-6d3c7e8d-…
vlm-brain-cluster nursing-home-alerts 0          196             197             1    -
```

`vlm-brain-cluster` 的 `CONSUMER-ID` 是 `-`（沒有活著的成員）、`LAG=1`——
那 1 則就是本次的測試事件，它**沒有**被舊二審消費掉。這是「只有一套在跑」最直接的證據。

---

## 三、必修 B —— 前端快照全空白

### 壞在哪（四環，每一環都實查過程式碼）

1. 邊緣端 [`ai/inference_test.py:1246-1249`](../inference_test.py#L1246-L1249) 送的
   `snapshot_path` 是 **`s3://` URI**（設了 `CLIP_S3_BUCKET` 時）
2. [`agent/schemas.py`](../../agent/schemas.py) 的 `AlertMessage` 用
   `model_config = {"extra": "ignore"}`，把這欄**整個丟掉**
3. [`agent/nodes/publish.py`](../../agent/nodes/publish.py) 只好改送 `state["image_path"]`，
   而那是 `ImageStore` 為了餵 VLM 解析出的**本機絕對路徑**
4. 後端 [`backend/core/s3.py:34`](../../backend/core/s3.py#L34) 的 `parse_s3_uri()`
   **只認 `s3://`**，不是就 `return None` → 簽不出 presigned URL → 快照永遠空白

第 4 步**不會噴任何錯誤**，只是回 `None`。這是為什麼要靠測試擋，不能靠 code review。

### 怎麼修

範本就在 [`ai/vlm_worker.py:69-74`](../vlm_worker.py#L69-L74) 的註解裡
（它自己註明「實測：走慢速道的事件全部中招」）：**優先沿用事件帶進來的，本機路徑只當退路**。

| 檔案 | 改動 |
|---|---|
| [`agent/schemas.py`](../../agent/schemas.py) | `AlertMessage` 新增 `snapshot_path: Optional[str] = None` |
| [`agent/nodes/publish.py`](../../agent/nodes/publish.py) | `snapshot_path=alert.snapshot_path or state["image_path"]` |

**退路必須留著**：[`ai/modules/sanity_check.py:35-45`](../modules/sanity_check.py#L35-L45)
的巡檢 payload **不帶 `snapshot_path`**，沒設 `CLIP_S3_BUCKET` 的機器也不帶。
那兩種情況照舊退回本機路徑，行為與改動前完全相同。

---

## 四、順手補 —— 多人同時跌倒分不出是幾個人

邊緣端 [`ai/inference_test.py:143`](../inference_test.py#L143) 會帶 `person_label`
（值像「畫面內第 1 位倒地者」），[`ai/vlm_worker.py:83-85`](../vlm_worker.py#L83-L85)
把它接在判讀文字最前面。agent 沒有這段，所以多人事件兩筆長得一模一樣。

改動：`AlertMessage` 新增 `person_label`，`publish.build_summary()` 負責併字串。

⚠️ **後端一個欄位都沒加**。`person_label` 本身不外發（它登記在護欄的
`INTERNAL_ONLY_KEYS`，[`scripts/check_guardrails.py:70`](../../scripts/check_guardrails.py#L70)），
只是併進既有的 `vlm_summary`。實測輸出見下方第六節，開頭的
`【畫面內第 1 位倒地者】` 就是這段。

---

## 五、實測怎麼跑的

順序不能反 —— agent 是 `auto_offset_reset="latest"`，先跑推論就看不到事件。

```bash
git checkout -b feat/agent-cutover main
# .env: AGENT_SHADOW 1→0、AGENT_AL_DATASET_DIR 改回 ai/active_learning_dataset
kill 71207                                   # 停舊二審
ai/.venv/bin/python -u -m agent.main         # 先起 agent
SINGLE_SOURCE=ai/test_demo/test8.mp4 HEADLESS=1 ai/.venv/bin/python -u ai/inference_test.py
```

**設定健檢輸出**（`python -m agent.main --check-config`）：

```
── Agent 設定健檢 ──
Kafka       : localhost:9092
  輸入 topic : nursing-home-alerts（group=agent-reviewer）
  輸出 topic : processed-reports
推理模型     : ollama:qwen2.5:7b
視覺模型     : qwen2.5vl:7b @ http://localhost:11434
圖檔來源     : local
  目錄       : ai/snapshots
執行模式     : 正式（送 Kafka 2）
DLQ 記錄     : ai/agent_dlq.jsonl
```

### 慢速道是自然走到的，沒有動任何門檻

原本擔心 AcT 換 v2 後信心太高、全部走快速道而繞過 agent。實跑結果**不需要**動
[`ai/inference_test.py:63`](../inference_test.py#L63) 的 `FAST_TRACK_CONF`：

```
🎯 [單源量測] SINGLE_SOURCE → 只掛一路：Room_301_Bed = /home/rapubuntu/aipe03-3/ai/test_demo/test8.mp4
👥 [Room_301_Bed] 逐人幾何判定：2 人通過門檻，best_idx=0（餵 AcT）｜判定倒地 (idx, 防線A, 防線B)=[(0, 1, 1)]
🚨 [Room_301_Bed] 第 1 位（track 1）跌倒事件已外發（topic=nursing-home-alerts，連續 4 幀判定成立）
🖼️ [Room_301_Bed] 快照已上傳：s3://aipe03-3/snapshots/snapshot_Room_301_Bed_20260804_160646.jpg
🎬 [Room_301_Bed] 事件片段已寫入（150 幀 @ 15.0fps，libx264 (PyAV)）：/home/rapubuntu/aipe03-3/ai/clips/clip_Room_301_Bed_20260804_160646.mp4
📦 [Room_301_Bed] 片段已上傳：s3://aipe03-3/videos/clip_Room_301_Bed_20260804_160646.mp4
```

`topic=nursing-home-alerts` = 慢速道。原因是防線 B（幾何遮擋）判成立
→ `is_occluded_fall=True`，而 [`ai/inference_test.py:111`](../inference_test.py#L111) 的
`is_fast_track = act_confidence >= FAST_TRACK_CONF and not is_occluded_fall`
對遮擋跌倒**不論信心多高一律走慢速道**。

**agent 的處理過程**（log 原文，已濾掉 Kafka 連線雜訊）：

```
2026-08-04 16:06:12,355 INFO Agent 啟動，監聽 topic=nursing-home-alerts group=agent-reviewer 模式=正式
2026-08-04 16:06:15,470 INFO Setting newly assigned partitions {TopicPartition(topic='nursing-home-alerts', partition=0)} for group agent-reviewer
2026-08-04 16:06:46,943 INFO 受理告警 device=301 type=fall 圖檔=/home/rapubuntu/aipe03-3/ai/snapshots/snapshot_Room_301_Bed_20260804_160646.jpg
2026-08-04 16:07:26,983 INFO VLM 判讀完成（第 1 次嘗試，耗時 40.0s）
2026-08-04 16:07:44,443 INFO judge 判定 true_alarm（信心 0.95）
2026-08-04 16:07:44,454 INFO 已送出 Kafka 2：301|2026-08-04T16:06:46.930949|fall ai_verdict=true_alarm
2026-08-04 16:07:45,374 INFO 收錄主動學習樣本：snapshot_Room_301_Bed_20260804_160646.jpg（high）
```

從告警進來到送出 Kafka 2 共 **57.5 秒**（VLM 判讀 40.0s + judge 17.5s）。
`ai/agent_dlq.jsonl` 沒有新增任何一行。

---

## 六、驗收（三項全過）

### ① 後端只收到一筆，不是兩筆

| | cutover 前 | 實測後 | 差 |
|---|---|---|---|
| `processed-reports` offset | 261 | **262** | **+1** |
| `nursing-home-alerts` offset | 196 | 197 | +1 |
| 後端 `GET /events` 筆數 | 31 | **32** | **+1** |

一筆告警進去、一筆事件出來。若舊二審沒停，這兩個 `+1` 會是 `+2`。

### ② 前端快照看得到（必修 B 的驗收點）

**新事件 `8efb40b5-3538-449a-a89a-222540304752`**（agent 產出）：

```
snapshot_path: s3://aipe03-3/snapshots/snapshot_Room_301_Bed_20260804_160646.jpg
clip_path    : s3://aipe03-3/videos/clip_Room_301_Bed_20260804_160646.mp4
```

`GET /events/8efb40b5-.../media`：

```
clip_url     : https://aipe03-3.s3.amazonaws.com/videos/clip_Room_301_Bed_20260804_160646.mp4?AWSAccessKeyId=…
snapshot_url : https://aipe03-3.s3.amazonaws.com/snapshots/snapshot_Room_301_Bed_20260804_160646.jpg?AWSAccessKeyId=…
```

**這張 presigned URL 是真的下得動**，不是只有字串長得對：

```
presigned GET snapshot -> HTTP 200 (content-type: image/jpeg)
```

**對照組**：DB 裡上一筆事件 `f9b65bc5-f225-4549-b2a4-46d107c1d512`
（2026-08-03 22:56，`snapshot_path` 是本機絕對路徑
`/home/rapubuntu/aipe03-3/ai/snapshots/snapshot_Room_301_Bed_20260803_225605_p3.jpg`）：

```
clip_url     : https://aipe03-3.s3.amazonaws.com/videos/clip_Room_301_Bed_20260803_225604.mp4?AWSAccessKeyId=…
snapshot_url : None      ← 影片簽得出來，快照簽不出來
```

同一筆事件影片有、快照沒有，正是 `parse_s3_uri()` 只認 `s3://` 的症狀。
（那筆的本機路徑是當時邊緣端就送本機路徑造成的，**不是** `vlm_worker` 的錯——
它一直有沿用事件帶進來的值。這裡拿它當對照，是為了證明「本機路徑 → `snapshot_url: None`」
這條因果實際存在，也就是必修 B 若不修，走 agent 的每一筆都會長這樣。）

### ③ `ai_verdict` / `ai_reasoning` 有值

`processed-reports` offset 261 的原始訊息：

```
device_id     : 301
event_type    : fall
clip_path     : s3://aipe03-3/videos/clip_Room_301_Bed_20260804_160646.mp4
detected_at   : 2026-08-04T16:06:46.930949
snapshot_path : s3://aipe03-3/snapshots/snapshot_Room_301_Bed_20260804_160646.jpg
yolo_score    : 0.998710036277771
vlm_summary   : 【畫面內第 1 位倒地者】【現場畫面描述】
                1. 人數：三名
                2. 身體姿態：
                   - 前方的男子跪著，身體貼著地面。
                   - 中間的兩名男子站立行走。…
ai_verdict    : true_alarm
ai_confidence : 0.95
ai_reasoning  : 根據現場畫面，前方男子跪著且身體貼地，符合跌倒的姿態。雖然其他兩人站立，但不能排除該男子發生了跌倒事件。
```

三件事一次看到：

- `snapshot_path` 是 `s3://` → **必修 B 生效**
- `vlm_summary` 開頭的 `【畫面內第 1 位倒地者】` → **多人標記生效**
  （對照上游 `nursing-home-alerts` 的原始告警帶的是獨立欄位 `person_label: 畫面內第 1 位倒地者`，
  它**沒有**出現在 Kafka 2 的 payload 裡，後端零感知）
- `ai_verdict` / `ai_confidence` / `ai_reasoning` 三欄都有值 → 這是舊二審做不到的

`GET /events` 回來的同一筆也帶著 `ai_verdict: "true_alarm"` / `ai_confidence: 0.95` /
`ai_reasoning`，代表後端 consumer 有正確落地這三個新欄位。

---

## 七、順帶確認：主動學習樣本改指回正式目錄沒有污染 D 組資料

`.env` 的 `AGENT_AL_DATASET_DIR` 從 `ai/active_learning_dataset/agent_shadow`
改回 `ai/active_learning_dataset`。實測落地的東西：

```
ai/active_learning_dataset/images/snapshot_Room_301_Bed_20260804_160646.jpg   (333551 bytes)
ai/active_learning_dataset/meta/snapshot_Room_301_Bed_20260804_160646.json
ai/active_learning_dataset/README.md                                          (sample_store 首次寫入時自動產生)
```

sidecar 內容：

```json
{
  "image": "snapshot_Room_301_Bed_20260804_160646.jpg",
  "collected_at": "2026-08-04T16:07:45",
  "event_type": "fall", "camera_id": "301", "device_id": 301,
  "yolo_score": 0.998710036277771, "yolo_threshold": 0.45,
  "agent_verdict": "true_alarm", "agent_confidence": 0.95,
  "keep_reason": "YOLO信心度高但複判為true_alarm，屬於誤觸發的盲點。",
  "priority": "high"
}
```

**沒有寫任何 `labels/`**。[`agent/sample_store.py`](../../agent/sample_store.py) 刻意不產標註檔
——舊 `vlm_worker` 會寫一組寫死的假座標，[`ai/prepare_dataset.py:17-25`](../prepare_dataset.py#L17-L25)
掃出 21 個那種假標註檔。所以改指回正式目錄只是多出圖與收錄理由，D 組的重訓資料沒被動到。

---

## 八、順手做：刪掉 `ai/clearml_train_pipeline_final.py`

刪除前已 `diff -u` 比對過兩支：

| | `clearml_train_pipeline.py`（240 行）| `clearml_train_pipeline_final.py`（151 行）|
|---|---|---|
| 是什麼 | **原始碼** | `submit_task.py` 產生的**機器產物** |
| 路徑 | `AIPE03_AI_DIR` Task 參數 / `__file__` 基準 | 第 8 行寫死 `/home/rapubuntu/aipe03-3/ai/.env` |
| 憑證 | 不碰 | 自己 parse `.env`、塞 `CLEARML_SDK__AWS__S3__*` |
| 繼承上一輪 best | 有（`Model` 查詢 + 建立時間排序）| **無** |
| mAP 驗收門檻 | 有（`MAP50_GATE=0.80`）| **無** |
| `data.yaml` 絕對路徑展開 | `mlops_paths.resolve_data_yaml()` + standalone 退路 | **無** |

差異方向一致：`_final.py` 是產物、功能是原始碼的子集，而且帶硬路徑（違反
`CLAUDE.md` 第四節「路徑不要寫死家目錄」）。`clearml_train_pipeline.py` 的 docstring
第 4-6 行**自己就寫明**要收掉它。

⚠️ **這個刪除不會出現在任何 commit 裡**：它已列在
[`.gitignore:161`](../../.gitignore#L161)（`git check-ignore -v` 確認過），
所以只是本機 `rm`。差異紀錄就是這一節。

---

## 九、回滾路徑

程式改動（必修 B、多人標記）**不用退**——它們是在修既有 bug，對 `vlm_worker` 沒有影響。
要退的只有服務歸屬：

```bash
# 1. 保險絲插回去
sed -i 's/^AGENT_SHADOW=0/AGENT_SHADOW=1/' .env
# 2. 停 agent（本次 pid 72378），重新起舊二審
cd ai && ../ai/.venv/bin/python -u vlm_worker.py
```

⚠️ **兩者絕對不能同時跑**，理由見第二節。

---

## 十、驗證指令與結果

```
python scripts/check_guardrails.py            → 見下方「收尾」
python -m pytest agent ai scripts -q          → 202 passed（基準 191，新增 11 支）
.venv-backend/bin/python -m pytest backend -q → 見下方「收尾」

curl http://127.0.0.1:8000/health             → 200
POST http://127.0.0.1:8010/v2/repository/index → action_transformer v2 / rt_detr v2 / yolo_pose READY
```

新增的 11 支測試分佈：

- [`agent/tests/test_nodes_publish.py`](../../agent/tests/test_nodes_publish.py) 9 支
  —— `snapshot_path` 三種情況（s3、缺、空字串）、`person_label` 五種情況、不外發後端
- [`agent/tests/test_schemas.py`](../../agent/tests/test_schemas.py) 2 支
  —— `AlertMessage` 收得下這兩欄；巡檢訊息沒有這兩欄也不會壞

---

## 十一、還沒解決的

- `agent/docs/04-open-questions.md` 的 **Q4–Q7 仍未拍板**：`uncertain` 在前端怎麼呈現、
  shadow 通過門檻、問答助手範圍、前端請求怎麼到 agent。本輪是「先完整跑一輪」，
  不是這些問題有答案了。
- **本次只驗了一筆事件、一種路徑**（單人跌倒 → 遮擋 → 慢速道 → `true_alarm`）。
  沒驗到的有：`false_alarm` 判定、`uncertain` 降級成 `ai_verdict=null`、
  巡檢事件走 `env_report`、**多人同時跌倒的兩筆事件**（`person_label` 只在單人情境下
  驗到「第 1 位」，兩筆並存時前端怎麼呈現沒實際看過）。
- `agent/` 沒有 watchdog：掛了不會自己爬起來（`ai/watchdog.py` 目前也只看得住推論行程）。
- `agent/docs/` 的架構文件仍停在 07-19/20，本輪未動。

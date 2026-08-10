# 下一階段待辦

**這份只放「還沒做完的」。** 已完成項目的完整紀錄搬到
[`docs/CHANGELOG-STAGES.md`](CHANGELOG-STAGES.md)（編號沿用，第 N 項還是第 N 項）。

Mac 本機環境的建置任務表在 [`docs/MAC_SETUP_WBS.md`](MAC_SETUP_WBS.md)。
不知道系統現在長什麼樣、哪裡是壞的 → [`docs/ARCHITECTURE.md`](ARCHITECTURE.md)。

---

## 待辦總覽

**分級**：🔴 P0＝現在就在漏報／誤判；🟠 P1＝成果做完了沒收割，或收割會炸；
🟡 P2＝已診斷／已設計，可排期。

| # | 項目 | 分級 | 狀態 |
|---|---|---|---|
| 9-4 | 體角判定的前提與俯視佈署不符 | 🔴 P0 | 📋 **已診斷，未修，最需要正視**（見下）|
| 11 | AcT 重訓成果的收割 | 🟠 P1 | 🧰 **工具與資料進來了，管線沒接、權重沒拿到**（本檔下方）|
| 12 | agent 二審尚未 cutover | 🟠 P1 | shadow log 停在 7/28、僅 4 筆，證據量不足（本檔下方）|
| 4 | Prometheus 導入 | 🟡 P2 | 📐 **只出設計，未接線**（本檔下方）|
| 13 | 離床／輪椅（座椅滑落）| 🟡 P2 | 📌 **本輪只埋伏筆，未實作**（本檔下方）|

已完成並驗證過的（紀錄在 [`docs/CHANGELOG-STAGES.md`](CHANGELOG-STAGES.md)）：
第 1 項 S3 上傳、第 2 項六大防線收斂 + 模組白名單、第 3 項 Triton GPU/CPU 對照、
第 5 項事件冷卻計時器、第 6 項 agent P2、第 7 項 `stream_channel` 改名、
第 8 項偵測畫面推流、第 9 項真攝影機實測（含 `normal_h_reference` 換來源重設）、
第 10 項 MLOps 進版控、第 14 項 VLM 二審模型切換至 `qwen2.5vl:7b`、
第 15 項 agent 的 `al_curator` 移除。

---

## 9-4：第 9 項裡**還沒修**的缺陷

第 9 項整項標【已完成】，它列的四個缺陷中缺陷一、二已修，**缺陷三（`normal_h_reference`
換來源不重設）也已於 2026-08-03 修掉**（分支 `fix/fall-cooldown-and-href-reset`，完整記錄
搬進了 [`docs/CHANGELOG-STAGES.md`](CHANGELOG-STAGES.md) 第 9 項缺陷三）。**只剩缺陷四還沒修**：

防線 A 的體角規則**隱含假設攝影機是水平視角**，但正式環境是公共區域**俯視**——俯視時
站著的人軀幹投影就接近水平，幾何特徵與臥倒完全相同，**調門檻無效**。屬模型調校，範圍不小。

**重要旁證**：實測中 AcT 時序分類判「正常」信心 0.93~1.00 **完全正確**，被騙的是兩條
手寫幾何規則。要調權重時這是依據。完整量測數據（含那組「髖部在影像上比肩膀還高」的座標）
見 [`docs/CHANGELOG-STAGES.md`](CHANGELOG-STAGES.md) 第 9 項缺陷四。

---

## 12.【未拍板】agent 二審尚未 cutover

正式二審仍是 `vlm_worker.py`（`AGENT_SHADOW=1`）。`ai/agent_shadow.jsonl` 只有 **4 筆、
停在 2026-07-28**，通過門檻的證據量嚴重不足；`agent/docs/04-open-questions.md` Q4–Q7
（`uncertain` 的前端呈現、shadow 通過門檻、問答助手範圍、前端請求怎麼到 agent）未拍板。
系統現況見 [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) §6.2。

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

## 11.【工具已進來、成果沒收割】AcT 重訓與降誤報

2026-08-03 把 `feat/ai-act-retrain` 的 21 顆非 hazard commit 移植進 main
（PR：`feat/act-retrain-onto-main`）。**那一批刻意沒有動 `ai/inference_test.py`
一個字**——進來的是離線量測工具鏈、AcT 重訓全套、50 份人工逐幀標註與六份評估報告。

所以「AcT 重訓讓誤報大幅下降」這件事，**目前只有工具和數據在 repo 裡，線上行為完全沒變**。
以下四件事沒做，做的時候要照順序。

### 11-1 ⚠️ 重訓後的權重不在版控裡（最先要解，其他三項都靠它）

[`ai/action_transformer_v2.run.json`](../ai/action_transformer_v2.run.json) 記著那一輪的
指標（val accuracy 0.9992、fall recall 0.9944），但 `action_transformer_v2.pth`
**本身沒進 repo**（`.gitignore` 的 `*.pth` 擋掉）。Triton 上跑的仍是舊的
`action_transformer`。

兩條路：
- 跟 ychsieh725 要那個 `.pth`
- 或用 [`ai/train/train_act.py`](../ai/train/train_act.py) 依同一份
  [`splits.json`](../ai/train/dataset/splits.json) 自己重訓（資料集標註都在 repo 裡了，
  只缺影片素材 CAUCAFall）

⚠️ `splits.json` 有一條不能踩的規則寫在檔案裡：`S<n+10>` 是 `S<n>` 的水平鏡像、
**是同一個人**，兩者必須在同一個 split，否則測試集洩漏而且指標看不出異常。

### 11-2 降誤報的兩個常數還沒套進管線

分支實測（13 支單一動作短片）：正常動作幀誤報率 **44.7% → 2.0%**，靠兩個改動：

| 改動 | 現況 |
|---|---|
| 遮擋高度門檻 `0.70 → 0.50`（[`ai/inference_test.py:921`](../ai/inference_test.py#L921)）| 未套用，main 仍是 0.70 |
| 幾何正常時不讓 AcT 單獨發動（[`ai/inference_test.py:1019`](../ai/inference_test.py#L1019) 的 `elif`）| 未套用，AcT 仍可單獨觸發 |

分支量到的代價也要一起看：跌倒片幀召回 67.1% → 41.5%。

**動手前先用這次進來的工具在 5060 Ti 上複驗**，不要照抄 Mac 上的數字：

```bash
ai/.venv/bin/python ai/batch_eval.py --modes geo-first --occ-height 0.50
ai/.venv/bin/python ai/tune_occlusion.py      # 掃門檻找取捨點
```

### 11-3 逐人 AcT 視窗（main 目前沒有）

main 的多人跌倒已經很完整（[`ai/inference_test.py:818-964`](../ai/inference_test.py#L818-L964)：
ByteTrack + 逐人身高基準 + 連續幀 debounce + 逐人閂鎖/復原 + 同位置去重 + 每人各一筆事件），
**但 AcT 時序仍然只餵「框最大的那個人」**，是單一 30 幀視窗。

分支的 [`ai/person_tracks.py`](../ai/person_tracks.py) 做到了「每個 track 各自一個
30 幀視窗與身高基準」，但那是離線版，且它整套多人邏輯比 main 現有的簡略
（沒有逐人身高、沒有去重、不是每人各一筆事件）。**不要照搬**——要做是把「逐人視窗」
這一項接到 main 既有的 `person_states` / `idx_to_track` 上，那是重寫不是移植。

⚠️ 接之前先想清楚 Triton 的 batch：現在 AcT 一幀最多問一次，改成逐人之後是 N 人 N 趟。
只有在「幾何已標記躺平/遮擋」時才問 AcT 的話，實務上每幀通常 0 次，`batch=1` 夠用；
但如果同時把 11-2 的 `ACT_ALONE_CAN_TRIGGER` 打開，就變成每人每幀都要問，
人多會掉幀，屆時要先把 AcT 重匯出成動態 batch。

### 11-4 ⚠️ 離線評估的躺平規則跟正式管線不一致

[`ai/fall_chain.py`](../ai/fall_chain.py) 的檔頭寫「常數全部對齊 `inference_test.py`」，
**但它對齊的是修正前的版本**：

| | 躺平（防線 A）的角度條件 |
|---|---|
| `fall_chain.py`（離線，`LYING_RULE_CURRENT`）| `body_angle < 40` |
| [`ai/inference_test.py:901`](../ai/inference_test.py#L901)（線上）| `min(angle, 180-angle) < 40` |

線上那條是 `249f132` 補的——只寫 `< 40` 會整個漏掉「頭朝左躺」（約 180°）那一半。
換句話說 **main 現行行為等同 `fall_chain` 裡的 `LYING_RULE_WIDE`**，不是 `CURRENT`。

分支自己量過三種規則（CAUCAFall test split，跌倒幀 181 / 正常影片幀 1583）：

| 規則 | 跌倒幀命中 | 正常幀誤報 |
|---|---|---|
| `current`（`<40`）| 16.6% | 5.9% |
| `aspect`（只看寬高比）| 14.9% | **0.1%** |
| `wide`（`<40` 或 `>140`，＝**線上現況**）| **22.7%** | 8.0% |

**影響**：拿 `batch_eval.py` / `local_pipeline_eval.py` 算出來的「躺平」會比線上保守，
數字不能直接當成線上表現。

**為什麼本輪兩邊都不改**：改 `fall_chain` 會讓一起移植進來的六份評估報告數字對不上
程式碼；改線上則是動偵測行為、而且會丟掉 `249f132` 修的東西。真要收斂時建議的順序是
先補一組線上規則的離線量測，再決定要不要往 `aspect` 走（那看起來是誤報最低的，
但召回也最低，要跟 11-2 一起評估）。

### 11-5 主動學習樣本進不了訓練（agent 那條已拆，`ai/` 那條還在）

`agent` 的 `al_curator` 已於 2026-08-10 移除（見
[`CHANGELOG-STAGES.md`](CHANGELOG-STAGES.md) 第 15 項），但**問題只是少了一個生產者**：

- `ai/active_learning_dataset/` 裡 **1037 張沒有標註的圖還在**，每次跑
  `ai/prepare_dataset.py` 都會被隔離一次（`隔離・沒有對應標註` → `_quarantine/images/`）。
  要嘛送進 Label Studio 補標，要嘛移走。**本輪刻意沒動這些檔案**
  （在 `.gitignore` 內、且刪資料不可逆）。
- 還在收樣本的是 [`ai/uncertainty_router.py:250`](../ai/uncertainty_router.py#L250) 的
  寫死區間 `0.35 ≤ yolo_score ≤ 0.85`，配 `package_active_learning_sample()` 寫的
  **假 YOLO-Pose 座標**（每張圖同一組數字，與畫面無關）。那 143 個 `labels/` 就是這樣來的
  —— **有標註，但標註是假的**。這比沒有標註更難發現。
- 也就是說：**目前這條迴路兩端都不通**，一端沒標註、一端標註是假的。
  接 AcT 重訓（第 11 項）之前要先把這件事講清楚。

---

## 13.【伏筆，本輪未實作】離床／輪椅（座椅滑落）

依 [`CLAUDE.md`](../CLAUDE.md) 第一節 2026-07-30 的決定，這兩項要收回來做，
`ai/modules/` 白名單已放行，但**本輪只寫這節文件**——不動 `ai/modules/`、不動護欄、
不撈檔案回來。這裡列「未來動工的人一次就對」需要知道的四件事。

### 1. 檔案怎麼取回——只在 git 歷史裡，不在版控中

`bed_exit.py` / `chair_slip.py` 於 `61c9f63` 被刪，`^` 是刪之前那顆（還有檔案的版本）：

```bash
git show 61c9f63^:ai/modules/bed_exit.py   > ai/modules/bed_exit.py
git show 61c9f63^:ai/modules/chair_slip.py > ai/modules/chair_slip.py
```

### 2. 兩個檔的契約狀況完全不同，動工前一定要先確認

`chair_slip.py` **乾淨**：只 `return True/False`，護欄會直接過，就是範本。

`bed_exit.py` **違約**：第 52 行 `producer.send('processed-reports', ...)` 自組 payload
直送 Kafka，欄位多 `alert_id`/`camera_id`/`severity`/`status`、少 `clip_path`/
`snapshot_path`——**復活後護欄的 `check_module_no_kafka()` 會直接擋下來**，就算過了護欄，
沒改的話送到後端也是 422 靜默丟棄。**必須先把 `producer.send(...)` / `producer.flush()`
整段拿掉，改成只 `return is_leaving_bed`**，外發統一交給主迴圈的 `route_by_confidence()`——
照 `chair_slip.py` 的樣子做就對了。

### 3. 接進來之前要先修的另一個坑：`rt_detr` 類別對照表

線上 `rt_detr` 鎖 v2，只有 **5 類**（`person`/`chair`/`sofa`/`bed`/`tv`，
見 `ai/data.yaml`），但 [`ai/triton_detr_client.py:15-20`](../ai/triton_detr_client.py#L15-L20)
的 `.names` 寫死的是 **COCO 80 類**——`names[cls_id]` 查出來的名字會是錯的
（例：v2 的 `cls_id=4` 是 `tv`，這裡會查成 COCO 的 `airplane`）。現在不會壞是因為
唯一會讀這張表的下游（`bed_exit`/`chair_slip`）已刪，沒人在用；離床要查 `bed`、
輪椅要查 `chair`，**兩者都吃這顆對照表**，復活前一定要先把 `names` 改成讀
`ai/data.yaml` 的類別映射，不能假設它是 COCO。

### 4. 復活模組時，三件事缺一不可（CLAUDE.md 已規定）

1. 改 `CLAUDE.md` 的白名單表，寫清楚為什麼收回這個決定
2. 改 [`scripts/check_guardrails.py`](../scripts/check_guardrails.py) 的 `MODULES_ALLOW`
3. **確認該模組不會自組 payload 外發**，外發一律回主迴圈的 `route_by_confidence()`
   （範本是 `chair_slip.py` 的做法）——`check_module_no_kafka()` 會機器強制第 2、3 類，
   但**護欄只擋 Kafka 外發，不會幫你檢查偵測邏輯對不對、或事件會不會誤報**，不要因為
   有機器擋就不看。

---

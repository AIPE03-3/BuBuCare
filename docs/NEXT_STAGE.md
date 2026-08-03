# 下一階段待辦

**這份只放「還沒做完的」。** 已完成項目的完整紀錄搬到
[`docs/CHANGELOG-STAGES.md`](CHANGELOG-STAGES.md)（編號沿用，第 N 項還是第 N 項）。

Mac 本機環境的建置任務表在 [`docs/MAC_SETUP_WBS.md`](MAC_SETUP_WBS.md)。
不知道系統現在長什麼樣、哪裡是壞的 → [`docs/ARCHITECTURE.md`](ARCHITECTURE.md)。

---

## 待辦總覽

| # | 項目 | 狀態 |
|---|---|---|
| 4 | Prometheus 導入 | 📐 **只出設計，未接線**（本檔下方）|
| 5 | 事件冷卻計時器 | ⏸ **本輪不執行**，卡多人追蹤（本檔下方）|
| 9-3 | `normal_h_reference` 換來源不重設 | 📋 **已診斷，未修**（見下）|
| 9-4 | 體角判定的前提與俯視佈署不符 | 📋 **已診斷，未修，最需要正視**（見下）|
| 11 | AcT 重訓成果的收割 | 🧰 **工具與資料進來了，管線沒接、權重沒拿到**（本檔下方）|

已完成並驗證過的（紀錄在 [`docs/CHANGELOG-STAGES.md`](CHANGELOG-STAGES.md)）：
第 1 項 S3 上傳、第 2 項六大防線收斂 + 模組白名單、第 3 項 Triton GPU/CPU 對照、
第 6 項 agent P2、第 7 項 `stream_channel` 改名、第 8 項偵測畫面推流、
第 9 項真攝影機實測、第 10 項 MLOps 進版控。

---

## 9-3 / 9-4：第 9 項裡兩個**沒修**的缺陷

第 9 項整項標【已完成】，但它列的四個缺陷**只修了兩個**。這兩個至今是壞的，
放在這裡是因為它們是待辦、不是歷史：

| # | 缺陷 | 為什麼還沒修 |
|---|---|---|
| 9-3 | 防線 B 的 `normal_h_reference` **只在 worker 開頭 10~40 幀校正一次**，之後永不更新 | 換攝影機／改構圖／斷線重連後就一直用舊值，症狀是「永遠紅燈」且畫面上看不出原因。修法方向已定（畫面尺寸變化時設回 `None`），沒動手 |
| 9-4 | 防線 A 的體角規則**隱含假設攝影機是水平視角**，但正式環境是公共區域**俯視** | 俯視時站著的人軀幹投影就接近水平，幾何特徵與臥倒完全相同 —— **調門檻無效**。屬模型調校，範圍不小 |

**9-4 的重要旁證**：同一次測試裡，AcT 時序分類判「正常」信心 0.93~1.00 **完全正確**，
被騙的是兩條手寫幾何規則。要調權重時這是依據。

完整量測數據（含那組「髖部在影像上比肩膀還高」的座標）見
[`docs/CHANGELOG-STAGES.md`](CHANGELOG-STAGES.md) 第 9 項缺陷三、缺陷四。

### 還沒解的：事件一次性閂鎖讓測試很難做

`vlm_triggered` 讓每個 worker 生命週期只發一次事件。實測時 AI 啟動 9 秒就被誤觸發、
把唯一額度用掉，後面真的躺下**完全不會再發事件**，一度以為是事件管線壞了。

這強化了第 5 項的必要性，也多了一個原本沒想到的理由：**不解開這個閂鎖，
現場調校與驗收測試幾乎沒辦法做** —— 每測一次就要重啟一次 AI。

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

---

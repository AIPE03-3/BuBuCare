# 系統架構總覽

**這份是給要理解整個系統的人看的**：資料怎麼流、每個元件負責什麼、為什麼這樣設計。

其他文件的分工：

| 文件                                     | 用途                                                           |
| ---------------------------------------- | -------------------------------------------------------------- |
| [`CLAUDE.md`](../CLAUDE.md)             | 動工前必讀的**硬規則**（模組白名單、契約邊界、金鑰分工） |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | 兩台開發機的協作規矩、護欄、分支流程                           |
| [`RUN_ON_MAC.md`](RUN_ON_MAC.md)     | macOS 上把系統跑起來的操作手冊                                 |
| [`NEXT_STAGE.md`](NEXT_STAGE.md)     | **還沒做完的**：待辦與各項狀態                                 |
| [`CHANGELOG-STAGES.md`](CHANGELOG-STAGES.md) | **已完成階段的紀錄**：做了什麼、為什麼、踩過哪些坑        |
| [`MAC_SETUP_WBS.md`](MAC_SETUP_WBS.md)  | macOS 本機環境的建置任務表與踩坑                               |
| **本檔**                           | **架構全貌與設計理由**                                   |

> **維護提醒**：這份文件的價值來自「與實作一致」。改動架構時請一起改這裡，
> 特別是第六節 —— 那節專門記錄「現況與規劃的差距」，過時的樂觀描述比沒有文件更糟。

---

## 一、系統在做什麼

長照機構的**跌倒偵測**系統。攝影機畫面進來，AI 判斷有沒有人跌倒，有的話通知護理站，
並留下影片證據供人工複判。複判結果回頭餵給模型重訓，形成主動學習迴路。

```
                    ┌──────────────── 邊緣端 ai/ ────────────────┐
攝影機 ──→ MediaMTX ─→│ inference_test.py                          │
（或 mp4）  （串流轉發）│   yolo_pose ─┐                              │
                     │   rt_detr ───┤→ 防線 A/B + AcT 時序分類 → 判定 │
                     │   action_transformer ─┘                     │
                     └──────────────┬─────────────────────────────┘
                                    │ route_by_confidence()
                    ┌───────────────┴────────────────┐
              快速道 │ AcT 信心 ≥ 0.90                │ 慢速道（其餘）
                    ↓                                ↓
         Kafka: processed-reports        Kafka: nursing-home-alerts
                    │                                ↓
                    │                    vlm_worker.py（VLM 二審）
                    │                    ／ agent/（LangGraph，shadow 中）
                    │                                │
                    └────────────────┬───────────────┘
                                     ↓
                    backend/（FastAPI）→ PostgreSQL (AWS RDS)
                                     ↓ SSE
                              frontend/（React）
```

事件影片與快照另外走 **S3**：邊緣端上傳，後端簽 presigned URL 給前端播放。

---

## 二、跟著一個事件走完全程

這是理解整個系統最快的路徑。

### 1. 邊緣端偵測（`ai/inference_test.py` 的 `camera_worker`）

三顆模型都跑在 **Triton**（不是本地載入），各自負責：

| 模型                          | 職責                                            |
| ----------------------------- | ----------------------------------------------- |
| `yolo_pose`                 | 人體骨架關鍵點（17 點）                         |
| `rt_detr`                   | 環境物件偵測（椅子、床、沙發…）                |
| `action_transformer`（AcT） | **時序**跌倒分類：30 幀視窗 → 是不是跌倒 |

判定不靠單一訊號，有三道：

- **防線 A**：肩髖體角 + 長寬比 → 判斷「躺倒」
- **防線 B**：幾何遮擋防禦（被桌椅擋住只露上半身時不誤判）
- **AcT**：30 幀（約 3 秒）視窗的時序分類

還有兩個防誤報機制：

- `FALL_CONSECUTIVE_FRAMES=4` —— **連續 4 個處理幀**都判倒地才算數。單幀就觸發的話，
  蹲著綁鞋帶的人會誤報（`test7.mp4` 第 0.27 秒實測到）
- **ByteTrack 跨幀身分**（`MULTI_PERSON_TRACK`）—— 逐人判定解決漏報，但 YOLO 的偵測索引
  每幀都可能換人，沒有身分就說不出「這是 A 的事件」。debounce 與追蹤是同一件事的兩半

### 2. 分流（`route_by_confidence()`）

```python
is_fast_track = act_confidence >= FAST_TRACK_CONF and not is_occluded_fall   # 0.90
```

| 信心             | 走哪                                     | 為什麼                              |
| ---------------- | ---------------------------------------- | ----------------------------------- |
| ≥ 0.90 且非遮擋 | **快速道** `processed-reports`   | 危急事件零延遲，直接落 DB，不等 VLM |
| 其他             | **慢速道** `nursing-home-alerts` | 交給 VLM 二審，確認後才進 DB        |

**這是整個系統最重要的設計決策**：不確定的事件寧可慢一點也要問清楚，確定的事件一秒都不能等。

### 3. 二審（慢速道才有）

VLM 讀事件快照 → 產生中文判讀 → 組成後端要的格式 → 送 `processed-reports`。

目前有**兩套實作併行**：

|             | `ai/vlm_worker.py`                | `agent/`                                                |
| ----------- | ----------------------------------- | --------------------------------------------------------- |
| 狀態        | **正式服務中**                | **shadow 模式**（`AGENT_SHADOW=1`）               |
| 架構        | 單檔流程 +`uncertainty_router.py` | LangGraph 圖，7 個節點                                    |
| Kafka group | `vlm-brain-cluster`               | `agent-reviewer`（刻意不同，才能併行）                  |
| 產出        | `vlm_summary`                     | 多帶`ai_verdict` / `ai_confidence` / `ai_reasoning` |

shadow 模式下 `agent/` 判定結果**只寫 jsonl 不送 Kafka**，兩者各自獨立消費同一個 topic。
上線策略是 shadow → 比對 → cutover，回滾只要反向操作。

### 4. 後端落地（`backend/`）

`kafka_consumer.py` 讀 `processed-reports` → `POST /events` → PostgreSQL（AWS RDS）→ SSE 推前端。

### 5. 前端（`frontend/`）

事件中心看卡片、監控頁看即時／偵測畫面、通報單、歷史查詢。
影片來源是後端用**唯讀金鑰**簽的 presigned URL。

---

## 三、為什麼是這些設計

### 3.1 模組不准自組 payload 外發

`ai/modules/` 底下的偵測模組**只能回傳訊號，不能自己送 Kafka**。

歷史教訓：曾有三個模組各自組 payload 直接 `producer.send('processed-reports', ...)`，
欄位對不上後端的 `EventCreateRequest`（多了 `alert_id`/`camera_id`/`status`，少了
`clip_path`/`snapshot_path`）→ **每一則都被後端 422 退件，而且是靜默的**。

現在由 [`scripts/check_guardrails.py`](../scripts/check_guardrails.py) 機器強制：
模組裡任何 `.send(...)` 都會被擋（認方法名不認變數名，改寫法躲不掉）。

**白名單可以隨階段調整，契約不能。** 詳見 [`CLAUDE.md`](../CLAUDE.md) 第一節。

### 3.2 兩組 S3 金鑰，刻意分開

| 金鑰                                                  | 誰用                                    | 權限 |
| ----------------------------------------------------- | --------------------------------------- | ---- |
| `S3_RW_*`                                           | `ai/inference_test.py` 上傳事件片段   | 讀寫 |
| `S3_REGION`/`ACCESS_KEY_ID`/`SECRET_ACCESS_KEY` | `backend/core/s3.py` 簽 presigned URL | 唯讀 |

最小權限。**不要把讀寫金鑰塞進後端那三個名字**，那會讓後端也拿到寫入權限。

### 3.3 Triton 的版本鎖是明確的，不靠隱式載入

`config.pbtxt` 一律寫 `version_policy: { specific { versions: [N] } }`。
曾經靠「Triton 自動載最大版本號」，結果一個載不起來的版本讓**整台 server 起不來**
（explicit 模式一顆倒全倒）。事故記錄在 [`ai/triton_repo/README.md`](../ai/triton_repo/README.md)。

⚠️ **權重不進版控**（`ai/triton_repo/*/[0-9]*/` 在 `.gitignore`），所以版本鎖只能指向
「每台機器都拿得到的版本」。鎖 v2 而別人只有 `1/` = 對方整台 Triton 起不來。

### 3.4 LLM 節點只判斷，副作用集中在純函式節點

`agent/` 的設計原則。Kafka、檔案寫入全部在純函式節點，LLM 節點只回答問題。
好處是分支邏輯可以單測，不必跑整張圖。

同樣的思路：通報單草稿刻意**不進 Kafka 路徑** —— 它是一次 LLM 呼叫（估 3–8 秒），
只在 `true_alarm` 時需要，也就是最該快的那條路，改成前端開表單時即時產生。
（另一個例子 `al_curator` 已於 2026-08-10 整個移除，見
[`CHANGELOG-STAGES.md`](CHANGELOG-STAGES.md) 第 15 項。）

---

## 四、MLOps 迴路

```
邊緣端事件快照
   ↓
Label Studio（人工標註／AI 預標註）
   ↓  inference_to_labelstudio_sdk.py 雙向同步
本地 YOLO 標籤 → prepare_dataset.py → detection_dataset/
   ↓  submit_task.py 排單
ClearML 佇列 → clearml-agent 咬單 → clearml_train_pipeline.py 訓練
   ↓  過門檻才標 best（mAP50 ≥ 0.80）
S3（權重）
   ↓  model_deployment_agent.py
Triton 熱載切版（服務不中斷）→ 可 --rollback
```

**門檻的作用是擋 `best` 標記，不是擋上傳**：沒過門檻的權重照樣上 S3 並標 `below-gate`，
但 `model_deployment_agent` 只抓「最新的 best」，所以練壞的模型上不了線。
沒有這個機制的話，模型會一輪一輪變差而且全程不報錯。

---

## 五、三個機器強制的硬規則

跑 `python3 scripts/check_guardrails.py`（pre-commit 與 CI 都會跑）：

1. **`ai/modules/` 白名單** —— 只准存在四個檔，也只准 import 這四個
2. **模組不准送 Kafka** —— 見 3.1
3. **`route_by_confidence()` 的 payload 欄位** —— AST 檢查 dict 的 keys

還有兩條寫在 `CONTRIBUTING.md` 但同樣重要：**路徑不要寫死家目錄**（用 `__file__` 基準或
環境變數）、**不要直接 push `test/main-integration`**。

---

## 六、⚠️ 現況與規劃的差距

**這節最重要。** 讀完前五節會覺得系統很完整，但以下是實際狀態：

### 6.1 已知未修的偵測缺陷

| 缺陷                                       | 狀態                                                                                                                    |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| **體角判定的前提與實際佈署場景不符** | 🔴 **未修，最需要正視**。正式環境是公共區域**俯視**鏡頭，而防線 A 的軀幹角條件在那個角度基本沒訊號，調門檻無效 |
| `normal_h_reference` 換來源不重設        | ✅ 2026-08-03 已修（分支 `fix/fall-cooldown-and-href-reset`）                                                          |
| 跌倒事件一次性閂鎖（整個行程只發一次）    | ✅ 2026-08-03 已修，改成每相機每事件類型的冷卻計時器（同一批分支）                                                     |

只剩體角一項還開著，追蹤在 [`NEXT_STAGE.md`](NEXT_STAGE.md) 9-4；
完整量測數據見 [`CHANGELOG-STAGES.md`](CHANGELOG-STAGES.md) 第 9 項、第 5 項。
**不要以為跌倒偵測在所有場景都可靠**——AcT 時序分類在俯視角度下判斷正確，
被騙的是兩條手寫幾何規則，是接下來調權重的依據。

**另一塊已做完但沒收割**：`feat/ai-act-retrain` 的 AcT 重訓成果（正式管線正常動作幀
誤報率 44.7%→2.0%）已於 2026-08-03 把離線工具鏈與資料移植進 main
（`feat/act-retrain-onto-main`），但**刻意沒有動 `ai/inference_test.py` 的偵測邏輯**——
權重不在版控裡、降誤報常數沒套進管線、逐人 AcT 視窗沒接。線上行為目前完全沒變，
細節與待辦順序見 [`NEXT_STAGE.md`](NEXT_STAGE.md) 第 11 項。同一次移植也把 main
既有的多人跌倒（ByteTrack + 逐人身高基準 + 每人各一筆事件）保留下來，是本輪唯一
接受過人工逐段合併的檔案。

**VLM 二審已切換**：2026-08-03 頭對頭 A/B 驗證後，`vlm_worker.py` 與 LangGraph 的
視覺模型都已從 `llava:latest` 切到團隊拍板的 `qwen2.5vl:7b`，理由與數據見
[`CHANGELOG-STAGES.md`](CHANGELOG-STAGES.md) 第 14 項。

**危險物品偵測（hazard）本輪未收**：程式碼完整留在 `feat/hazard-detection` 分支未合併。
兩個技術理由：線上 `rt_detr` 鎖 v2 只有 5 類（person/chair/sofa/bed/tv），
`HAZARD_CLASSES={"knife","scissors"}` 需要的 COCO 80 類抓不到；且合併要跑 DB
migration（專案無 alembic，`init_db.py` 的 `create_all` 只建新表不加欄位），
正式 PostgreSQL 沒加對應欄位會直接寫入失敗。

### 6.2 兩套二審併行，agent 尚未 cutover

`agent/` 在 shadow 模式，正式服務的是 `vlm_worker.py`。
`agent/docs/04-open-questions.md` 還有 Q4–Q7 未拍板（`uncertain` 的前端呈現、shadow 通過門檻、
問答助手範圍、前端請求怎麼到 agent）。

### 6.3 `agent/docs/` 的架構文件已過時（07-19/20 寫的）

- `01-architecture.md` 描述的邊緣端含「音訊融合 + 椅子滑落/離床/徘徊模組」——
  那五個模組在 **07-27 已刪除**
- `schemas.py:47-49` 說 `vlm_worker` 每筆都 fallback 成 `device 101` ——
  [vlm_worker.py:52](../ai/vlm_worker.py#L52) 早就改成直接讀 `device_id` 了

文件本身寫得非常仔細（連設計取捨的實測數字都有），但**日期停在改動之前**。

### 6.4 兩台開發機跑的不是同一套

|             | 5060 Ti（正式）          | macOS（開發）                          |
| ----------- | ------------------------ | -------------------------------------- |
| `rt_detr` | `tensorrt_plan`（GPU） | **`rt_detr_onnx`**（ONNX/CPU） |
| Triton      | GPU                      | CPU，2.3~2.4 fps                       |
| 重訓        | GPU                      | CPU，只驗流程                          |

照 `RUN_ON_MAC.md` 學會的是 Mac 版本，**不等於正式環境的架構**。

### 6.5 沒有第一手驗證的部分

以下元件**從沒實際跑過**，只有讀過程式碼：

- `ai/webhook_receiver.py`（LS 標註到門檻 → 自動觸發重訓）→ 所以目前 MLOps 迴路是**半自動**，
  要手動跑 `submit_task.py`
- `ai/watchdog.py`、`ai/monitor_kafka.py`、`ai/bench_triton.py`、`ai/get_latency_diff.py`
- `agent/` 的 `qa/`（事件問答助手，尚未建立）

### 6.6 MLOps 迴路跑通 ≠ 模型有變好

2026-07-30 在 macOS 上驗證整條迴路時：

- 標註是 **AI 預標註自動接受**的，不是真人審核
- 訓練是 **14 張圖 1 epoch**，mAP50 = 0.535（**沒過 0.80 門檻**）
- 部署的是那顆練壞的模型（驗完已回滾）

那次驗的是**管線通不通**，不是模型品質。看到「MLOps 跑通了」不要誤會成模型在進步。

---

## 七、自己跑一次

理解架構最好的方式是把它跑起來看事件從頭走到尾。

- macOS：照 [`RUN_ON_MAC.md`](RUN_ON_MAC.md)
- Linux + NVIDIA：照 [`CONTRIBUTING.md`](CONTRIBUTING.md) 第一節

建議的觀察順序：

1. 先只跑 **P1 核心鏈**（Triton + Kafka + backend + frontend），用 mp4 觸發一次跌倒
2. 開 Kafka UI（`:8080`）看訊息實際長什麼樣 —— 比讀 schema 直觀
3. 再起 `vlm_worker`，觀察慢速道多了什麼欄位
4. 最後才碰 MLOps（很吃資源，而且與核心鏈解耦）

> **順序陷阱**：`vlm_worker` 是 `auto_offset_reset='latest'`，**一定要先起它再跑推論**，
> 否則它看不到已經發生的事件。

# 01 — 架構設計

> ## ⚠️ 本文件寫於 2026-07-19/20，下面「現況資料流」那節已經過時
>
> §1 描述的邊緣端含「音訊融合 + 椅子滑落／離床／徘徊模組」，那五個模組已在
> **2026-07-27 刪除**（見根目錄 [`CLAUDE.md`](../../CLAUDE.md) 第一節的白名單決策），
> `event_type` 從此恆為 `"fall"`。
>
> **§2 之後的目標資料流、LangGraph 圖設計、節點職責與 `graph.py` 的實作仍然一致**
> （2026-07-30 逐項核對過），那部分可以放心讀。
>
> 系統當前全貌與「現況 vs 規劃」的差距見 [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md)。

## 1. 現況資料流（實測程式碼確認，非猜測）

```
邊緣端 ai/inference_test.py
  YOLO-Pose + Action Transformer + 音訊融合 + 椅子滑落/離床/徘徊模組
  └─ 觸發告警（act_confidence > 0.55，或躺臥/遮蔽/音訊融合路徑）─ inference_test.py:247-252
       ├─ 快車道（conf > 0.90 或椅子滑落，非遮蔽）→ 直送 Kafka 2，跳過 VLM ─ L317-335
       └─ 慢車道（其餘，即 0.55–0.90 與遮蔽/躺臥觸發）
            └─ Kafka 1: topic=nursing-home-alerts @ localhost:9092
       ※ conf ≤ 0.55 完全不發 ← 已拍板放寬至 0.35，見 §7
            訊息: { event_type, camera_id, image_filename, yolo_score,
                    yolo_threshold, detected_at, clip_path? }
            └─ ai/vlm_worker.py（★ 本次要被取代的元件）
                 1. 讀本機圖檔（路徑寫死 /Users/albert/... ← 既有問題）
                 2. 依 event_type 二選一 prompt → ollama.chat(model='llava:latest')
                 3. 寫死規則 0.35 ≤ yolo_score ≤ 0.85 → 打包主動學習樣本
                 4. 組 EventCreateRequest 格式 → Kafka 2: topic=processed-reports
                      └─ backend/kafka_consumer.py → POST /events (X-API-Key)
                           └─ DetectEvent 進 DB: status=pending, verdict=NULL
                                └─ SSE /stream → 前端彈窗
                                     └─ 人工複判: PATCH /events/{id}/verdict
                                        （true_alarm → 通報流程；false_alarm → resolved）
```

「人工複判」的具體動作 = 看快照 + VLM 報告 → 給 verdict。**這就是 Agent 要接管的環節。**

## 2. 目標資料流

```
Kafka 1: nursing-home-alerts
  └─ agent/（新服務，取代 vlm_worker.py）
       LangGraph 圖（見 §3）
       └─ Kafka 2: processed-reports
            訊息 = 現有格式 + 新增欄位（ai_verdict / ai_confidence /
                   ai_reasoning，見 03-contracts.md）
            └─ backend/kafka_consumer.py（不改）→ POST /events
                 └─ events service 套用非對稱策略：
                      ai_verdict == true_alarm  → 建檔時直接 verdict=true_alarm
                      ai_verdict == false_alarm → verdict 留 NULL，只存建議
                 └─ 前端：
                      true_alarm  → 照常彈窗（通報單草稿改為開啟表單時即時產生）
                      false_alarm → 事件卡顯示「AI 建議：誤報 + 理由」，一鍵確認鈕
```

兩個功能走獨立入口，**都不經 Kafka**：

- 事件問答助手：前端 → `POST /agent/ask` → 唯讀查詢工具 → 回答
- 通報單草稿：前端開啟通報單時 → 即時產生（已拍板 2026-07-20，理由見下）

**為什麼草稿不走 Kafka**：草稿是一次 LLM 呼叫（估計 3–8 秒），且只在 `true_alarm` 時需要——
正好是最該快的那條路。塞進 Kafka 訊息等於讓跌倒通知等草稿產生完才發得出去。
改成開表單時即時產生後，告警路徑上完全沒有草稿的成本，而且草稿產生失敗也只是表單空白，
不會影響告警本身。

## 3. LangGraph 圖設計

### 3.1 State（單一事件流經全圖的資料結構）

```python
class AgentState(TypedDict):
    # 輸入（來自 Kafka 1，Pydantic 驗證後）
    alert: AlertMessage            # 原始告警
    image_path: str                # 解析後的絕對路徑（來自 config，不寫死）

    # 中間產物
    vlm_report: str | None         # VLM 原始判讀
    vlm_retries: int               # VLM 重試次數
    judge_retries: int             # judge 判 uncertain 時的補問次數
    judge_max_retries: int         # 補問上限（組圖時綁入）
    followup: str | None           # 補問內容

    # 產出
    verdict: Literal["true_alarm", "false_alarm", "uncertain"]
    confidence: float              # Agent 對自己判定的信心 0~1
    reasoning: str                 # 判定理由（繁中，給人看）

    # 流程控制
    error: str | None              # ingest 擋掉壞資料時標記原因，後續節點短路
```

（通報單草稿不在 state 裡：已改為前端開表單時即時產生，不經這張圖。見 §2）

### 3.2 節點與流向

> 以下與 `agent/graph.py` 的實作一致（可用 `compiled_graph.get_graph().draw_mermaid()` 覆核）。

```
ingest ─┬─(drop：壞資料/缺圖)──────────────────→ END
        ├─(routine：巡檢事件)──→ env_report ─────────┐
        └─(review：告警事件)───→ vlm_analyze → judge ─┤
                                     ↑  (失敗重試≤2)  │
                                     └─ followup ←────┤(retry_vlm：uncertain 且未達補問上限)
                                                      │
                                     (publish：其餘)───┴→ publish（Kafka 2）→ END
```

| 節點 | 型態 | 職責 |
|---|---|---|
| `ingest` | 純函式 | Pydantic 驗證訊息、經 ImageStore 解析圖檔（等待 ≤2s）、壞資料進 DLQ log |
| `vlm_analyze` | 工具節點 | 呼叫 Ollama `llava`（沿用現有 prompt 精神），失敗重試 2 次 |
| `judge` | **LLM 節點** | 綜合 yolo_score、VLM 報告、事件類型 → structured output（verdict/confidence/reasoning）。`uncertain` 且未達補問上限 → 走 `followup` 回 `vlm_analyze` |
| `followup` | 純函式 | 組追問內容、累加補問次數 |
| `env_report` | 工具節點 | 巡檢報告整理（沿用現況功能，不加戲）；不做真假判定 |
| `publish` | 純函式 | 組 Kafka 2 訊息（現有格式超集）、冪等去重、flush、記 log。**圖的終點** |

分流不是獨立節點，而是條件邊（`route_after_ingest` / `route_after_judge` 兩個純函式），
所以分支邏輯可以單測，不必跑整張圖。

**`al_curator` 已於 2026-08-10 移除**（原本排在 `publish` 之後，理由是它多花 3.2 秒的
LLM 呼叫而產出沒人讀）。移除的理由比排序更根本：那 3.2 秒換來的樣本沒有標註，
`ai/prepare_dataset.py` 一律隔離，回訓一筆都用不到。完整緣由與取回方式見
[`docs/CHANGELOG-STAGES.md`](../../docs/CHANGELOG-STAGES.md) 第 15 項。

「對告警沒必要的 LLM 節點排在 `publish` 之後或移出圖外」這條原則仍然有效，
現存的例子是通報單草稿（§2）。`test_publish_是圖的終點` 接手釘住拓樸——
LangGraph 對「節點沒有出邊」與「publish 後面被接上新節點」都不會報錯，沒有斷言就沒有防線。

設計原則：**LLM 節點只做判斷，副作用（Kafka、檔案）全部集中在純函式節點**，方便單元測試與重放。

### 3.3 安全策略落點

- `judge` 產出 `uncertain` 且重試耗盡 → 一律降級為 `false_alarm` 建議？**否。** 一律以 `ai_verdict=null` 送出（等同現況、交回人工），寧可不判也不誤判。
- Agent 端永遠只產「建議」；把建議轉成正式 verdict 的權力在 backend（單一守門點，見 03-contracts.md §3）。

## 4. LLM 選型（已拍板 2026-07-19：開發期純 Ollama）

| 用途 | 決定 | 說明 |
|---|---|---|
| 視覺複判（VLM） | **Ollama `llava`（維持現況）** | 已驗證可跑、零成本、影像不出門；Agent 只是把它從主角降為工具 |
| Agent 推理（judge/草稿/問答） | **開發期：地端 Ollama**（任一支援 structured output 的文字模型；勿用 llava 當推理腦）。**已實測可用：`qwen2.5:7b`** | 在開發者本機開發測試，零 API 成本。已知代價：地端小模型的 structured output 穩定度低於雲端，因此 judge 的解析失敗降級路徑（→ ai_verdict=null 交回人工）是**必要防線，不是加分項** |
| 未來正式環境 | **未拍板**（續留地端或切雲端 API 再議） | factory 抽象保證切換只改環境變數：`AGENT_LLM=ollama:qwen3` ↔ `AGENT_LLM=anthropic:claude-haiku-4-5-20251001` |

實作要求：所有 LLM 呼叫走同一個 factory（`agent/llm.py`，`init_chat_model` 抽象），模型名稱、API key、base_url 全部進 `agent/config.py` 讀環境變數，**程式碼中不得出現寫死的模型名或路徑**（順手修掉 vlm_worker 寫死 `/Users/albert/...` 的既有問題）。預設值即開發環境，無任何雲端依賴也能完整跑通。

### 4.1 實作現況：沒有用到 tool calling（2026-07-20）

規劃當初把「支援 tool calling」列為推理模型的必要條件，但**實作到目前為止一次都沒用到**——
沒有 `bind_tools`、沒有 `@tool`、沒有 `ToolNode`。所有 LLM 節點都只用 structured output（填一張表）。

原因：複判流程是固定的（取圖 → 看圖 → 判定 → 發布），沒有「要不要查資料、先查哪個」
的決策空間。把固定流程交給 LLM 自由決定，只會多一個不穩定來源，地端小模型尤其。
圖的邊由程式決定，LLM 只在被叫到時回答問題。

**對選型的影響：不必再把 tool calling 當硬性條件**，只要模型能穩定吐 structured output 即可。
唯一真正需要 tool calling 的是 P5 的事件問答助手（「該查哪張表、下什麼條件」是開放式的），
那是一張獨立的小圖，屆時可以單獨為它挑模型。

## 5. 程式碼落點

> 標 ⬜ 者尚未建立，其餘為現況（2026-07-20）。

```
agent/                        # 頂層套件（與 backend/、ai/ 平行）
├── __init__.py
├── config.py                 # 環境變數集中（Kafka、LLM、圖檔來源、閾值）
├── llm.py                    # LLM factory（init_chat_model 抽象）
├── image_store.py            # ImageStore 抽象（local / s3 兩種後端，見 §8）
├── schemas.py                # AlertMessage / ProcessedReport / AgentState / structured output
├── prompts.py                # 所有 prompt 集中，節點只管流程不管措辭
├── jsonl.py                  # DLQ 與 shadow 判定記錄的落地工具
├── graph.py                  # LangGraph 圖組裝
├── nodes/                    # 每節點一檔，純邏輯與副作用分層
│   ├── ingest.py
│   ├── vlm.py
│   ├── judge.py
│   ├── env_report.py
│   └── publish.py
├── qa/                    ⬜ # 事件問答助手（P5，獨立小圖 + 唯讀 DB 工具）
├── docs/                     # 本資料夾（規劃文件與程式碼放一起）
├── main.py                   # Kafka consumer 迴圈入口（對齊 backend/kafka_consumer.py 的分層風格）
└── tests/
```

通報單草稿沒有對應節點：已改為前端開表單時即時產生，不在這張圖裡（見 §2 與 03 檔 §5）。

依賴管理：根目錄 `pyproject.toml`（uv），已加入 `langgraph`、`langchain`、`langchain-ollama`、`ollama`。
雲端 provider 套件待 Q1 拍板後再加——`init_chat_model` 是 lazy import，屆時 `uv add` 即可，程式碼零改動。

## 6. 上線策略（shadow → cutover）

1. **Shadow mode**：Agent 用不同 consumer group 併行消費 Kafka 1，判定結果只寫 log/檔案、**不送 Kafka 2**；`vlm_worker.py` 照常服務。
2. 比對 N 筆（建議 ≥30 筆真實或壓測告警）Agent 建議 vs 人工 verdict，確認方向正確。
3. **Cutover**：停 `vlm_worker.py`、Agent 開啟 publish。回滾 = 反向操作，5 分鐘內可還原。

## 7. 邊緣端觸發門檻調整（已拍板：放寬）

慢車道（進 Agent 複判）的觸發門檻由 **0.55 放寬至 0.35**；快車道 **>0.90 不動**。

調整後的信心度分帶：

| act_confidence | 現況 | 調整後 |
|---|---|---|
| > 0.90（或椅子滑落） | 快車道直送 Kafka 2 | **不變**（危急事件零延遲） |
| 0.55 – 0.90 | 慢車道 → VLM | 慢車道 → Agent 複判 |
| 0.35 – 0.55 | **不發（缺口）** | **慢車道 → Agent 複判**（放寬的部分） |
| < 0.35 | 不發 | 不發（雜訊層，避免灌爆 VLM） |

選 0.35 的依據（皆為程式碼既有數字，非新發明）：

1. `is_ai_thinking_fall` 的門檻就是 0.35（inference_test.py:247）——系統既有的「開始懷疑」語意線。
2. 主動學習收錄下限就是 0.35（vlm_worker.py:136）——現況 0.35–0.55 樣本根本送不出來，此規則形同虛設；放寬後才真正生效。
3. 降門檻只增加告警、不減少，方向與非對稱安全原則一致。

具體改動（邊緣端組員的程式碼，需協調，一行）：

```python
# inference_test.py:252，0.55 → EDGE_TRIGGER_THRESHOLD（環境變數，預設 0.35）
elif len(frame_window) == 30 and pred_class == 0 and act_confidence > 0.35: should_trigger_fall = True
```

注意事項：
- 建議改成環境變數而非直接改數字，shadow 期間可隨時調回 0.55 比對告警量。
- 放寬後告警量會上升（幅度未知，無實測數據），P2.4 shadow 階段需實測 Agent + llava 的吞吐是否跟得上；跟不上再議（提高門檻或加佇列背壓）。

## 8. 圖檔存取抽象（已拍板 2026-07-19：ImageStore 雙後端）

背景：圖檔有兩份——**S3 一份**（團隊已有 boto3 唯讀驗證，region `ap-northeast-1`，見 `gcp_vm_environment/test_sample/test_readonly_s3.py`）、**albert 本機硬碟一份**。Agent 不綁定特定機器：開發者本機要能測，換機器部署只改環境變數。

```python
# agent/image_store.py
class ImageStore(Protocol):
    def resolve(self, image_filename: str) -> str:
        """回傳本機可讀的絕對路徑；取不到丟 ImageNotFound（由 ingest 節點接住進 DLQ）"""

class LocalImageStore:   # AGENT_IMAGE_SOURCE=local
    # 在 AGENT_IMAGE_BASE_DIR 下找檔案，等待 ≤2s（沿用現況行為）

class S3ImageStore:      # AGENT_IMAGE_SOURCE=s3
    # 從 AGENT_S3_BUCKET/AGENT_S3_PREFIX 下載到本機暫存目錄後回傳路徑
    # 憑證走標準 AWS 環境變數/credentials 檔，程式碼不碰金鑰
```

| 環境變數 | 開發（本機測試） | 部署範例（與邊緣端不同機） |
|---|---|---|
| `AGENT_IMAGE_SOURCE` | `local` | `s3` |
| `AGENT_IMAGE_BASE_DIR` | 本機測試圖目錄 | —（不用） |
| `AGENT_S3_BUCKET` / `AGENT_S3_PREFIX` | —（不用） | 依 S3 存放約定填 |

設計原則：
- `ingest` 節點只認識 `ImageStore.resolve()` 介面，**不知道也不在乎圖從哪來**——換部署位置零程式碼改動。
- VLM（Ollama）吃本機路徑，所以 S3 後端一律「先下載到暫存再交給 VLM」，兩種後端對下游完全同型。
- 開發期用 `local` + 一批測試圖即可端到端跑通，不需要 S3 憑證。
- 待確認細節（不擋工）：S3 上圖檔的 key 命名約定是否等於 `image_filename`（邊緣端上傳邏輯歸組員，實作 S3 後端前對一次即可）。

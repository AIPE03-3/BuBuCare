# AI Agent 複判系統 — 規劃文件

> 本資料夾是「AI Agent 取代人工複判」功能的完整規劃，供實作模型（或工程師）閱讀後直接動工。
> 規劃日期：2026-07-19。**目前僅規劃，尚未實作。**

## 目標一句話

用 LangGraph 打造一個 Agent，取代現有 `ai/vlm_worker.py`：消費 Kafka 告警、指揮 VLM 複判、產出 verdict 建議與通報單草稿，並依「非對稱半自動」安全策略回寫系統。

## 閱讀順序

| 檔案 | 內容 | 給誰看 |
|---|---|---|
| [01-architecture.md](01-architecture.md) | 現況/目標資料流、LangGraph 圖設計、LLM 選型、安全策略 | 先讀，建立全貌 |
| [02-wbs.md](02-wbs.md) | 分期 WBS、任務拆解、驗收標準、依賴關係 | 動工前照表施工 |
| [03-contracts.md](03-contracts.md) | Kafka 訊息格式、後端欄位擴充、API 契約 | 實作時對照 |
| [04-open-questions.md](04-open-questions.md) | 未拍板事項與已知風險 | 動工前逐項確認 |

## 已拍板的決策（2026-07-19 與需求方確認）

| 決策點 | 結論 |
|---|---|
| 介入位置 | **取代 `ai/vlm_worker.py`**：Agent 消費 Kafka 1（`nursing-home-alerts`），VLM 降為 Agent 的工具節點，產出送 Kafka 2（`processed-reports`），後端契約向下相容 |
| 決策權限 | **非對稱半自動**：判 `true_alarm` → 自動確認並升級通報；判 `false_alarm` → 只寫建議欄位，需人工一鍵確認才關閉（漏報代價是人命，寧可多報） |
| 延伸功能 | ① 通報單自動草稿 ② 事件問答助手。**值班日報不做。**（原本還有 ③ 主動學習樣本篩選，已於 2026-08-10 移除，見 [`CHANGELOG-STAGES.md`](../../docs/CHANGELOG-STAGES.md) 第 15 項）|
| 邊緣端觸發 | **放寬**：慢車道門檻 0.55 → 0.35（對齊既有懷疑線與主動學習下限，做成環境變數）；快車道 >0.90 直送不動。詳見 01 檔 §7 |
| Agent LLM | **開發期純地端 Ollama**（開發者本機，零 API 成本）；factory 抽象保留，未來續留地端或切雲端 API 只改環境變數，不改程式碼。詳見 01 檔 §4 |
| 部署與圖檔 | Agent **不綁定特定機器**。圖檔雙源：S3 有一份、albert 本機硬碟有一份 → 以 ImageStore 抽象（`local` / `s3` 兩種後端），開發者本機可測、換機器部署只改環境變數。詳見 01 檔 §8 |
| 技術框架 | LangGraph（需求方指定） |
| 通報單草稿產生時機（2026-07-20） | **前端開啟通報單時即時產生，不走 Kafka**。草稿是一次 LLM 呼叫且只在 true_alarm 時需要，塞進 Kafka 訊息會讓跌倒通知等草稿產完。詳見 03 檔 §5 |
| 慢節點與告警路徑的關係（2026-07-20） | **對告警沒必要的 LLM 節點一律排在 publish 之後或移出圖外**。現存的例子是通報單草稿移出 Kafka 路徑（另一個例子 `al_curator` 已於 2026-08-10 整個移除）|

## 不可退讓的原則

1. **Never break userspace**：Kafka 2 輸出訊息必須是現有格式的超集，`backend/kafka_consumer.py` 不改也能跑。
2. **安全非對稱**：任何情況下 Agent 不得自動把事件關成誤報。
3. **可退回**：Agent 掛掉時，重新啟動舊的 `vlm_worker.py` 即可還原現況（cutover 前先跑 shadow mode 驗證）。

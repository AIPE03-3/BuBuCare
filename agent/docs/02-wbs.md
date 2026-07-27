# 02 — WBS（工作分解結構）

> 估時單位：人日（1 人日 = 一位工程師專注一天）。P0→P2 為 MVP 必要路徑；P3–P5 可獨立排期、互不依賴。
> 每期結束都有可跑、可驗收的成果（MVP 迭代原則）。

## 總覽

| 期別 | 內容 | 估時 | 依賴 | MVP |
|---|---|---|---|---|
| P0 | 基礎建設與契約（含 ImageStore 雙後端） | 2.5 | — | ✅ |
| P1 | 複判核心（LangGraph 圖） | 4 | P0 | ✅ |
| P2 | 後端/前端整合 + 邊緣端門檻放寬 + shadow 驗證 + cutover | 4.5 | P1 | ✅ |
| P3 | 通報單自動草稿 | 2 | Q7 | — |
| P4 | 主動學習樣本篩選 | 1.5 | P1 | — |
| P5 | 事件問答助手 | 3 | P0 | — |
| | **合計** | **17.5** | | MVP=11 |

---

## P0 — 基礎建設與契約（2 人日）

| # | 任務 | 產出 | 驗收標準 |
|---|---|---|---|
| 0.1 | 建立 `agent/` 套件骨架 + uv 依賴（langgraph、langchain、langchain-ollama、ollama；雲端 provider 待 Q1 拍板後再加，`init_chat_model` 是 lazy import，屆時 `uv add` 即可、程式碼零改動） | 目錄結構如 01 檔 §5 | `uv sync` 成功；`python -m agent.main --help` 可執行 |
| 0.2 | `config.py`：Kafka/LLM/圖檔路徑/閾值 全數環境變數化 | config 模組 + `.env.example` | 無任何寫死路徑或模型名；缺必要變數時啟動報清楚的錯 |
| 0.3 | `llm.py`：LLM factory（`init_chat_model` 抽象；**預設 `ollama:qwen3`**，`AGENT_LLM` 可切雲端） | factory + 煙霧測試 | 預設值下無任何雲端依賴可跑；切換環境變數即換後端，零程式碼改動 |
| 0.4 | `schemas.py`：AlertMessage（Kafka 1 入）、Kafka 2 出（含新欄位）、各節點 structured output 的 Pydantic 模型 | schemas 模組 | 以 03-contracts.md 的範例訊息通過驗證；壞資料丟明確錯誤 |
| 0.5 | 測試骨架：pytest + fake LLM / fake Kafka 注入點 | `agent/tests/conftest.py` | 節點可在無網路、無 Kafka 下被單測 |
| 0.6 | `image_store.py`：ImageStore 抽象，local 後端完整實作 + s3 後端（boto3 下載到暫存；見 01 檔 §8） | image_store 模組 + 測試 | local：開發機測試圖可解析；s3：mock boto3 下下載/缺檔路徑有測試；兩後端對 ingest 同型 |

## P1 — 複判核心（4 人日）

| # | 任務 | 產出 | 驗收標準 |
|---|---|---|---|
| 1.1 | `ingest` 節點：訊息驗證、經 ImageStore 解析圖檔（缺圖跳過記 log，不認識具體後端） | nodes/ingest.py + 測試 | 現有 vlm_worker 處理的訊息樣本 100% 通過；缺圖不 crash；僅依賴 ImageStore 介面 |
| 1.2 | `vlm_analyze` 工具節點：Ollama llava 呼叫、重試 2 次、逾時保護 | nodes/vlm.py + 測試 | mock ollama 下重試/逾時路徑皆有測試 |
| 1.3 | `judge` 節點：structured output（verdict/confidence/reasoning/severity）+ uncertain 補問迴圈 | nodes/judge.py + 測試 | fake LLM 下四種 verdict 路徑皆可走通；uncertain 重試耗盡 → ai_verdict=null |
| 1.4 | `env_report` 節點：巡檢事件分流（維持現況功能） | 巡檢路徑 + 測試 | `Routine_Environment_Sanity_Check` 訊息產出巡檢報告、不觸發複判 |
| 1.5 | `publish` 節點 + `graph.py` 組圖 + `main.py` consumer 迴圈 | 可執行的完整服務 | 端到端：餵一筆 Kafka 1 測試訊息 → Kafka 2 收到相容格式訊息 |
| 1.6 | Shadow mode 開關（`AGENT_SHADOW=1`：只寫 log 不 publish） | 開關 + 結果記錄檔 | shadow 下 Kafka 2 零訊息、判定記錄完整落地（JSON lines） |

## P2 — 後端/前端整合 + 上線（4 人日）

| # | 任務 | 產出 | 驗收標準 |
|---|---|---|---|
| 2.0 | 協調邊緣端組員：慢車道觸發門檻 0.55 → 0.35，做成環境變數 `EDGE_TRIGGER_THRESHOLD`（依據見 01 檔 §7；程式碼歸邊緣端組員，一行改動） | inference_test.py 修改 | 0.35–0.55 區間事件可進 Kafka 1；環境變數可隨時調回 0.55 |
| 2.1 | 後端：`EventCreateRequest` + `DetectEvent` 增加 `ai_verdict`/`ai_confidence`/`ai_reasoning`（皆 optional，向下相容）+ DB 遷移 | models/router 修改 + 遷移腳本 | 舊格式訊息（無新欄位）照常建檔；既有測試全綠 |
| 2.2 | 後端：非對稱策略落在 events service —— `ai_verdict=true_alarm` 建檔即 `verdict=true_alarm`；`false_alarm` 只存建議 | service 修改 + 測試 | 兩種路徑 + null 路徑各有測試；**不存在任何自動關閉事件的程式路徑** |
| 2.3 | 前端：事件卡/詳情顯示 AI 建議徽章 + reasoning；false_alarm 建議附「確認誤報」一鍵鈕（走既有 PATCH /verdict） | UI 元件修改 | 建議與理由可見；一鍵確認後事件正常關閉；無 AI 建議的舊事件顯示不變 |
| 2.4 | Shadow 驗證：收集 ≥30 筆告警比對 Agent 建議 vs 人工 verdict，產出比對報告 | 比對報告（md） | true_alarm 召回率 100%（不漏報）；整體同意率達團隊可接受水準（見 04 檔 Q5） |
| 2.5 | Cutover：停 vlm_worker、Agent 開 publish、監控一天；撰寫回滾 SOP | 上線紀錄 + SOP | 事件正常入庫與彈窗；SOP 演練過一次回滾 |

## P3 — 通報單自動草稿（2 人日）

| # | 任務 | 產出 | 驗收標準 |
|---|---|---|---|
> **2026-07-20 調整**：草稿改為前端開表單時即時產生，不走 Kafka（見 03 檔 §5）。
> 原因：草稿是一次 LLM 呼叫且只在 true_alarm 時需要，塞進 Kafka 訊息會讓跌倒通知等它產完。
> 連帶影響：P3 不再依賴 P2 的 DB 欄位（草稿不存），但依賴 Q7（後端如何觸發 agent）。

| 3.1 | 草稿產生器：依事件資料 + VLM 描述產出草稿（欄位對齊前端 `ReportFormPage`） | 草稿模組 + 測試 | 草稿欄位 100% 對齊前端表單 schema |
| 3.2 | 後端 `POST /agent/draft`（沿用既有登入驗證）：取事件資料 → 產草稿 → 回傳 | API + 測試 | 需登入才能用；事件不存在回 404；產生失敗回明確錯誤而非半成品 |
| 3.3 | 前端：ReportFormPage 開啟時索取草稿、顯示產生中狀態、標示「AI 草稿，請核對」 | UI 修改 | 人工可整段改寫；未核對不能送出；草稿產生失敗時表單仍可正常手動填寫 |

## P4 — 主動學習樣本篩選（1.5 人日）

| # | 任務 | 產出 | 驗收標準 |
|---|---|---|---|
| 4.1 | `al_curator` 節點：LLM 判斷樣本回訓價值，取代 0.35–0.85 寫死規則 | nodes/al_curator.py + 測試 | 輸出 `{keep, reason, priority}`；打包沿用現有 `active_learning_dataset/` 目錄格式（相容既有下游） |
| 4.2 | 收錄理由寫入樣本 sidecar JSON，供日後回訓挑選 | metadata 檔 | 每筆收錄樣本都有機器可讀的理由與優先級 |

## P5 — 事件問答助手（3 人日）

| # | 任務 | 產出 | 驗收標準 |
|---|---|---|---|
| 5.1 | 唯讀 DB 查詢工具（白名單表：detect_events/devices/locations；強制 company_id 過濾） | qa/tools.py + 測試 | 工具層物理上無法執行寫入；SQL 注入測試通過 |
| 5.2 | 問答小圖：問題 → 工具查詢 → 繁中回答（含引用 event_id） | qa/graph.py + 測試 | 「昨晚 3 號房發生什麼事？」類問題可正確回答；查無資料時明說、不編造 |
| 5.3 | 後端 `POST /agent/ask`（沿用既有登入驗證）+ 前端問答入口 | API + UI | 需登入才能問；回答附事件連結 |

---

## 里程碑檢核

- **M1（P0+P1 完）**：`agent/` 可端到端消化測試告警，shadow 記錄落地 → 可 demo 圖的執行軌跡
- **M2（P2 完）= MVP 上線**：Agent 正式取代 vlm_worker，人工只剩「確認誤報」一鍵
- **M3（P3–P5 完）**：全功能

## 風險與緩解（實作時注意）

| 風險 | 緩解 |
|---|---|
| llava 判讀慢/不穩 | vlm_analyze 設逾時 + 重試上限；耗盡 → ai_verdict=null 交回人工 |
| 地端 Ollama structured output / tool calling 不穩（開發期主用模式） | 解析失敗 → ai_verdict=null 降級是必要防線（P1.3 驗收必測）；shadow 階段統計解析失敗率，過高再評估換模型或上雲端 |
| 圖檔路徑跨機器不一致（vlm_worker 既有寫死路徑問題） | P0.6 ImageStore 抽象（local/s3 雙後端，見 01 檔 §8），換部署位置只改環境變數 |
| Kafka 重複消費造成重複事件 | publish 前以 `camera_id + detected_at + event_type` 做冪等鍵記錄 |
| Agent 誤判 false_alarm | 架構層防死：Agent 無權關事件，backend 亦無自動關閉路徑（P2.2 驗收明文檢查） |

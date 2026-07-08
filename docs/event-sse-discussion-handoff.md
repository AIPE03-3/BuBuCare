# 事件通報 + SSE 功能討論交接文件

> ✅ **此功能已完成實作**（2026-07-03）。6 個端點全數上線、53 個測試通過、
> 正式 PostgreSQL 已完成建表/遷移/種子資料。
>
> - **最終設計**：`docs/superpowers/specs/2026-07-02-event-sse-design.md`（spec 為準）
> - **實作計畫**：`docs/superpowers/plans/2026-07-02-event-sse-implementation.md`（10 個任務全數完成，含執行時變更註記：ENUM 欄位改用原生 SQLAlchemy Enum）
> - **現況與 API 一覽**：見 `CLAUDE.md`
>
> 本文件僅保留「當初為什麼這樣設計」的決策紀錄，供日後回顧。

---

## 一、功能範圍

在 fulilian-backend（通報層 FastAPI）新增「跌倒事件」的完整流程：

1. 判斷層偵測到跌倒 → 事件進後端 → 存 PostgreSQL
2. 後端用 **SSE** 即時推播給前端中控站
3. 前端值班人員確認：真實跌倒 or 誤報
4. 真實跌倒 → 指派照護員處理 → 追蹤到「已結案」

---

## 二、技術決策（附理由）

| 決策 | 結論 | 理由 |
|--|--|--|
| 事件怎麼進後端 | **組員確定會引入 Kafka**。這次採「**先設計好介面、用 POST /events 模擬**」 | 把「收到事件」的處理邏輯抽成共用函式 `handle_incoming_event()`（在 `event_service.py`），POST 端點和未來的 Kafka consumer 都呼叫它。等組員的 Kafka 環境（topic: `vlm.verdicts`）好了再接上，**核心邏輯完全不用改**，只是多一個事件入口 |
| 即時推播技術 | **先只做 SSE** | 護理站電腦本來就一直開著。Web Push 之後可「加上」而非「換掉」——SSE 管畫面即時更新，Web Push 管網頁沒開時的系統通知，兩者不衝突 |
| SSE 廣播方式 | **全域連線池**（記憶體 list 維護所有連線，事件進來廣播給每一條，在 `sse.py`） | 單機夠用、程式乾淨。未來擴展可換 Redis Pub/Sub |
| 多客戶端支援 | **做多客戶端**（連線池） | 不只為了多人同時用，也為了健壯性：重新整理頁面時會短暫出現 0 條或 2 條連線，連線池能優雅處理 |
| 存 DB 和廣播順序 | **先存 DB，成功後才廣播** | 保證資料不遺失；若存 DB 失敗直接回錯，什麼都沒發生 |
| 事件狀態設計 | **status（進度）與 verdict（判定結果）拆兩欄** | 早期草稿是單欄狀態機（unverified→true_alarm→resolved），spec 修訂成兩欄：`status`=pending/in_progress/resolved 管進度、`verdict`=true_alarm/false_alarm 管人工判定，語意不混在一起 |
| user_account vs staff | **沿用既有 `user_account` 表（加 company_id 欄位），另建 `staff` 表** | `user_account`=有登入帳號、操作中控站的人；`staff`=被指派去現場的照護員（記在 `detect_events.staff_id`）。兩者是同一群護理師，但職責分開兩張表 |
| 模型回訓 | **不是後端的工作** | 後端只負責把誤報資料存好（事件 ID、時間、S3 路徑），ML pipeline 另外撈 Hard Negative Pool 重新訓練 |
| 多租戶（companies） | **schema 支援（company_id），邏輯先不做** | 本輪只有預設公司 id=1，未來擴多間安養院不用改表 |

### ⭐ Kafka 的架構重點（未來接入時看這裡）

```
現在：
  判斷層 ──POST /events──▶ [handle_incoming_event()] ──存DB──▶ SSE 廣播

未來（組員 Kafka 好了之後，只加不改）：
  判斷層 ──▶ [Kafka topic: vlm.verdicts] ──▶ FastAPI 背景 consumer ──┐
                                                                      ├─▶ [handle_incoming_event()] ──存DB──▶ SSE 廣播
  （POST /events 保留，可當測試/備援入口）───────────────────────────┘
```

**設計原則：事件「入口」（POST / Kafka consumer）和事件「處理」（存 DB + 廣播）拆開。** Kafka 接上時只是新增一個入口，處理邏輯（`event_service.py`）零改動。

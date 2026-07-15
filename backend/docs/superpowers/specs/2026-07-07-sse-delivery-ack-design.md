# SSE 送達確認 + 重推保護 — 設計規格

> 日期：2026-07-07
> 狀態：已與使用者逐段確認完成
> 前置：`backend/docs/superpowers/specs/2026-07-02-event-sse-design.md`（事件 + SSE 主體）

---

## 1. 目標與範圍

前端環境不保證穩定，SSE 推播可能漏接。新增送達確認 + 重推：前端回報收到，後端沒收到 ack 就自動重推。

**不在範圍內**：多 worker / Redis 共享（單一程序有效，見 §6）、Web Push、前端定時重抓（前端自理）。

---

## 2. 訊號來源

後端單方無法得知前端是否收到（物理限制），需前端主動回報。前端收到 SSE 後由程式自動打 ack，非人工。

`notified_at` 語意：任一前端 ack 即蓋章（單台或少數幾台中控站，不分裝置記錄）。

---

## 3. 資料庫改動

`detect_events` 新增：

| 欄位 | 型別 | 說明 |
|--|--|--|
| `notified_at` | `DateTime`, nullable, 預設 NULL | NULL = 尚無回報；有值 = 第一次被 ack 的時間 |

用時間戳不用布林：同樣表達「有無」，另帶「何時收到」供診斷送達延遲。與 `last_login_time` 同 pattern。

---

## 4. 新端點 `POST /events/{event_id}/ack`

| 項目 | 內容 |
|--|--|
| 權限 | 需登入（JWT header，同 `/events`） |
| 行為 | `notified_at` 為 NULL 才蓋現在時間（已有值不動） |
| 回應 | 200 + `{"status": "ok"}`；不回事件內容（前端不需要，送達狀態只記後端 DB 給計時器用） |
| 錯誤 | 事件不存在回 404 |
| 呼叫者 | 前端收到 SSE `event_created` 後自動呼叫 |

---

## 5. 重推計時器（asyncio 背景任務）

背景任務 `watch_delivery` 定義在 [service.py](../../../backend/events/service.py)；由 [router.py](../../../backend/events/router.py) 的 `create_event` 在 `handle_incoming_event` 廣播後啟動（`asyncio.create_task`）。放路由層而非 `handle_incoming_event` 內：後者是同步函式、被測試直接呼叫時無 event loop，於內部 `create_task` 會爆 `RuntimeError`。間隔 **10 秒**、最多 **3 次**（+10 / +20 / +30 秒）。

```
最多重複 3 次：
   睡 10 秒
   重查事件（背景任務開自己的 DB session）
   notified_at 有值？      → 停
   status 已離開 pending？  → 停（有人處理＝已送達）
   都沒有                  → 重推 event_created 同一份，續下一輪
```

重推沿用 `event_created`，不另發新名。前端以 `event_id` 去重（有則更新、無則新增），重推即安全的重複。

**可測試性**：抽純函式 `is_delivered(db, event_id) -> bool`（True=可停），計時器只負責睡與呼叫。

| 情境 | 期望 |
|--|--|
| `notified_at` 有值 | True |
| `status` 非 pending | True |
| 皆無 | False |

背景任務接受 session factory，測試不啟動計時器、不實際等 10 秒。

---

## 6. 已知限制

計時器與 SSE 連線池皆存記憶體，僅單一程序有效。多 worker 上線時一併改 Redis，記入 `docs/future-work.md`。

---

## 7. 序列化

`serialize_event` 增回 `notified_at`（前端 / 除錯用）。

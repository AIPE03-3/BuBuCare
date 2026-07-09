# Kafka Consumer 設計（processed-reports → POST /events）

## 目標

新增 `kafka_consumer.py`：一支獨立行程，消費 Kafka topic `processed-reports`，
每則訊息轉打現成的 `POST /events`，由 FastAPI 完成寫 DB + SSE 廣播。

## 為什麼走「打 HTTP」而非直接呼叫 handle_incoming_event（方案 B）

`sse.py` 的 `pool` 是 FastAPI 行程內的記憶體單例，`broadcast` 用 `asyncio.Queue.put_nowait`
投遞到屬於該行程事件迴圈的信箱。若 consumer 是獨立行程直接呼叫 `handle_incoming_event`，
它的 `pool` 是另一個空實例，broadcast 投不到前端連著的信箱——DB 有資料但 SSE 靜默失效。

方案 B 讓 FastAPI 行程自己做 broadcast，SSE 正常。附帶好處：欄位驗證、`detected_at`
字串轉 datetime、忽略多餘欄位（如 `image_filename`）、`watch_delivery` 重推，全部由
`POST /events` 現成路徑處理，consumer 不重寫。

代價：需開兩支行程（uvicorn + consumer）、consumer 需帶 `X-API-Key`、多一跳本機 HTTP。

> 未來擴充：多台 web 時方案 B 會破（POST 只進其中一台）。正解是 consumer 直接呼叫
> `handle_incoming_event` + 用 Redis Pub/Sub 取代記憶體 `pool` 讓 broadcast 跨行程
> （sse.py 註解已預告）。本次不做；因兩者都是「獨立 consumer 行程」，屆時 consumer 主結構幾乎不動。

## 資料流

```
albert 的 AI（producer，他負責）
  → Kafka topic: processed-reports
    → kafka_consumer.py（本次新增）
      → POST /events（帶 X-API-Key）
        → handle_incoming_event → 寫 DB → SSE 廣播 → 前端
```

## 訊息契約

以「真正 producer 送的欄位」為準（`inference_test.py` 快速道路 / `vlm_worker.py` 二審），
**不以 `monitor_kafka.py` 為準**（該檔欄位過時、與真正 producer 矛盾）。

訊息為 JSON，欄位對齊 `EventCreateRequest`：`device_id`、`event_type`、`clip_path`、
`detected_at`、`snapshot_path`、`yolo_score`、`yolo_threshold`、`vlm_summary`、`severity`。
多餘欄位（如 `image_filename`）由 Pydantic 自動忽略，consumer 不處理。

## 錯誤處理（at-least-once）

依 FastAPI 回應分三類，分辨「一時失敗」與「毒訊息」：

| 情況 | 判定 | 動作 |
| --- | --- | --- |
| 201 建立成功 | `ok` | commit（前進） |
| 400 / 422（裝置不存在、驗證失敗） | `poison` | log 記錄 + commit（跳過，避免堵住 partition） |
| 訊息非合法 JSON | `poison` | log + commit |
| 5xx / 連不到 / timeout | `retry` | 不 commit，睡幾秒重打同一則（server 恢復前不掉件） |

- `enable_auto_commit=False`，處理成功才手動 commit，達成 at-least-once。
- 毒訊息本次僅 log（留一個處理毒訊息的掛勾函式，之後可升級為 dead-letter queue，主結構不動）。
- 簡化：`retry` 為原地阻塞重試，適用單一 consumer；多 consumer group 的長時間阻塞議題不在本次範圍。

## 函式結構

| 函式 | 職責 | 碰外部 |
| --- | --- | --- |
| `classify_response(status_code)` | 回應碼 → `"ok"`/`"poison"`/`"retry"` | 否（純邏輯） |
| `handle_raw_message(raw, post_fn)` | 解析一則 → 呼叫注入的 `post_fn` → 回傳決定 | 否（靠注入） |
| `build_consumer()` | 建立 KafkaConsumer | 是 |
| `run()` | 主迴圈：收訊息、依決定 commit/重試、Ctrl+C 收工 | 是 |

`post_fn` 依賴注入：正式跑傳「真的打 /events」的函式，測試傳假的，免真 Kafka/server 即可測邏輯。

## 設定（.env / .env.example）

| 變數 | 預設 | 用途 |
| --- | --- | --- |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka broker 位址 |
| `EVENTS_URL` | `http://localhost:8000/events` | 要打的自家端點 |
| `EVENT_API_KEY` | （已存在） | 打 /events 的鑰匙 |

## 測試（TDD）

純邏輯免真 Kafka/server：

- `classify_response`：201→ok；400/422→poison；500→retry。
- `handle_raw_message`（傳假 `post_fn`）：合法 JSON+201→ok；+400→poison；+網路錯誤→retry；非法 JSON→poison。
- `build_consumer` / `run` 刻意寫薄、幾乎無邏輯，不納入單元測試。
- 可選整合測試：`post_fn` 指向 FastAPI TestClient + 測試 DB，驗證事件落 DB。

## 動到的檔案

- 新增 `kafka_consumer.py`
- 新增 `tests/test_kafka_consumer.py`
- 修改 `.env.example`（加 `KAFKA_BOOTSTRAP_SERVERS`、`EVENTS_URL`）與本機 `.env`
- 修改 `pyproject.toml`：加 `kafka-python`（未安裝）；HTTP client 用 `httpx`（已安裝，但目前在 dev 群組，需移到正式 `dependencies`，因 consumer 是正式程式非測試）
- 不動 `event_service.py` / `event_routes.py` / `models.py` / `sse.py` / `main.py`

## 不在本次範圍（待辦）

- **clip_path / snapshot_path 是 albert 本機路徑、非 S3**：前端無法開啟，需與 albert 對齊 S3 上傳流程。
- **event_type 用詞不一致**：快速道路送 `fall`/`chair_slip`，二審送 `Fall_With_VLM_Resolved` 等長句，需與 albert 敲定固定對照表。
- Dead-letter queue（毒訊息留存可重播）。
- consumer 容器化、方案 D（Redis Pub/Sub）水平擴充。

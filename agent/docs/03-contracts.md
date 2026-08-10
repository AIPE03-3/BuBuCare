# 03 — 資料契約

> 原則：Kafka 2 輸出 = 現有格式的**超集**。舊欄位一個不動、一個不少，新欄位全部 optional。
> `backend/kafka_consumer.py` 與既有 `POST /events` 在不改動的情況下必須照常運作。
>
> **2026-07-27 例外**：`severity` 與 `yolo_threshold` 已從 Kafka 2 輸出移除。後端在
> 2026-07-19（commit `1bbb585`）就把這兩欄從 `detect_events` 與 `EventCreateRequest`
> 整組拿掉了（理由見 `backend/docs/superpowers/specs/2026-07-19-event-table-redesign-design.md`：
> 「不再需要」，嚴重度概念改用 `verdict_by` / `resolved_by` 取代）。接收端自己都沒有這兩欄，
> 繼續送不叫相容，只是被 Pydantic（預設 `extra="ignore"`）靜默丟掉。
> `yolo_threshold` 仍留在 **Kafka 1**（AI 內部），見 §1。

## 1. Kafka 1 輸入：`nursing-home-alerts`（既有，不改）

> **2026-07-20 更正**：本節原本的範例訊息是理想化的，與邊緣端實際送出的格式不符
> （原範例有 `camera_id: "101"`、`event_type: "Fall_Detected"`，兩者都不存在於真實訊息）。
> 依原範例寫出的 schema 會讓 **100% 的真實訊息驗證失敗進 DLQ**。
> 以下內容改為直接從邊緣端程式碼抄錄。**動工前請以程式碼為準，不要相信這裡的文字。**

Kafka 1 上有**兩種格式**，來自兩個不同的發送者：

### 1.1 跌倒/滑落告警 —— `ai/inference_test.py:341`

```jsonc
{
  "device_id": 301,                     // int，邊緣端已從 camera_id 算好（Room_301_Bed → 301）
  "event_type": "fall",                 // 或 "chair_slip"（注意：不是 Fall_Detected）
  "clip_path": "test_demo/test1.mp4",   // ⚠️ 整支「來源影片」路徑，不是事件片段，也沒有時間偏移
  "detected_at": "2026-07-19T15:30:00",
  "snapshot_path": "/abs/path/snapshot_Room_301_Bed_20260719_153000.jpg",  // 邊緣端本機絕對路徑
  "image_filename": "snapshot_Room_301_Bed_20260719_153000.jpg",
  "yolo_score": 0.72,
  "yolo_threshold": 0.45,               // 只走 Kafka 1（AI 內部），judge prompt 比大小用，不外發後端
  "vlm_summary": "【AI 信心度不足】已觸發大模型二審…"    // 佔位文字，會被 Agent 的判讀覆蓋
}
```

**沒有 `camera_id` 這個欄位。**

### 1.2 定時環境巡檢 —— `ai/modules/sanity_check.py:35`

```jsonc
{
  "alert_id": "RTN_Room_301_Bed_1753000000",
  "device_id": 301,
  "event_type": "Routine_Environment_Sanity_Check",
  "detected_at": "2026-07-19T15:30:00",
  "camera_id": "Room_301_Bed",          // 有這個欄位，但值是非數字字串
  "yolo_score": 1.0,                    // 巡檢固定給滿分
  "image_filename": "snapshot_Room_301_Bed_20260719_153000.jpg",
  "severity": "low",
  "status": "PENDING_VLM_ROUTE"
}
```

**沒有 `yolo_threshold`、沒有 `clip_path`。**

### 1.3 Agent 的解析規則

`AlertMessage` 的 `device_id` 解析順序：

1. 直接讀 `device_id`（邊緣端已算好且正確）
2. 沒有才從 `camera_id` 抽數字（算法與邊緣端一致：`Room_301_Bed` → `301`）
3. 兩者都給不出編號 → 驗證失敗進 DLQ，**不硬塞假的 device_id**

多餘欄位（`snapshot_path`、`alert_id`、`status`、`severity`…）一律忽略，不因其存在而拒收。
（跌倒/滑落告警已不再送 `severity`；`ai/modules/sanity_check.py` 的巡檢訊息還在送，忽略即可。）
驗證失敗 → 記入 DLQ log（JSON lines），不 crash、不阻塞後續訊息。

## 2. Kafka 2 輸出：`processed-reports`（超集擴充）

```jsonc
{
  // ===== 既有欄位：名稱、型別、語意完全不變（vlm_worker.py 現況） =====
  "device_id": 101,                     // int，camera_id 轉換，非數字 fallback 101
  "event_type": "Fall_Detected",
  "clip_path": "/vids/fallback.mp4",
  "detected_at": "2026-07-19T15:30:00", // ISO 8601
  "snapshot_path": "/data/snapshots/snapshot_101_20260719_153000.jpg",
  "yolo_score": 0.72,
  "vlm_summary": "【安養中心緊急通報…】…",  // VLM 原始報告，欄位語意不變
  // severity 與 yolo_threshold 曾在此，已隨後端 2026-07-19 的清理移除（見本檔開頭說明）

  // ===== 新增欄位：全部 optional，舊 consumer 忽略也不壞 =====
  "ai_verdict": "true_alarm",           // "true_alarm" | "false_alarm" | null（uncertain 降級）
  "ai_confidence": 0.87,               // 0~1，Agent 對判定的信心
  "ai_reasoning": "VLM 確認人員倒臥於床邊地面，姿態與跌倒相符…"  // 繁中，給人看
}
```

**通報單草稿不在這則訊息裡**（已拍板 2026-07-20）：草稿改為前端開啟通報單時即時產生，
不經 Kafka。理由是「對告警沒必要的 LLM 呼叫不要擋在通知前面」——草稿是一次 LLM 呼叫（估計 3–8 秒），
只在 `true_alarm` 時需要，正好是最該快的那條路，塞進訊息等於讓跌倒通知等草稿。詳見 §5。

## 3. 後端擴充（P2）

### 3.1 `EventCreateRequest`（backend/events/router.py）新增 optional 欄位

```python
ai_verdict: Optional[Literal["true_alarm", "false_alarm"]] = None
ai_confidence: Optional[float] = None   # 0~1
ai_reasoning: Optional[str] = None
```

### 3.2 `DetectEvent`（backend/core/models.py）新增欄位 + DB 遷移

```python
ai_verdict: Mapped[Optional[str]] = mapped_column(
    Enum("true_alarm", "false_alarm", name="event_ai_verdict", create_constraint=True), nullable=True
)
ai_confidence: Mapped[Optional[float]] = mapped_column(Float)
ai_reasoning: Mapped[Optional[str]] = mapped_column(Text)
```

### 3.3 非對稱策略（唯一守門點：events service 建檔邏輯）

| ai_verdict | 建檔行為 | 之後 |
|---|---|---|
| `true_alarm` | `verdict = "true_alarm"`，status 照常 `pending` | 照常彈窗 + 通報流程（Agent 已代人按下「確認為真」） |
| `false_alarm` | `verdict = NULL`（**不關事件**），建議存於 ai_* 欄位 | 前端顯示建議 + 一鍵確認鈕，人按了才走既有 PATCH /verdict |
| `null` / 缺欄位 | 完全等同現況（純 pending） | 純人工複判，向下相容 |

**明文禁止**：任何程式路徑不得因 `ai_verdict=false_alarm` 自動將事件設為 resolved 或 verdict=false_alarm。

## 4. 事件問答助手 API（P5）

```
POST /agent/ask          # 沿用既有登入驗證（Bearer token）
Request:  { "question": "昨晚 3 號房發生什麼事？" }
Response: { "answer": "…（繁中，含 event_id 引用）", "event_ids": ["uuid", ...] }
```

工具層約束：唯讀連線；白名單表 `detect_events` / `devices` / `locations`；一律強制 `company_id` 過濾；查無資料時回「查無紀錄」，不得編造。

## 5. 通報單草稿（P3）—— 即時產生，不經 Kafka

**已拍板 2026-07-20**：草稿不隨 Kafka 2 訊息落地，改由前端開啟通報單時即時向後端索取。

```
前端開啟通報單 → POST /agent/draft { "event_id": "..." }（沿用既有登入驗證）
                    → 後端取出該事件的 vlm_summary / event_type / location / detected_at
                    → 產生草稿 → 回傳
```

好處：

- **告警路徑上零成本**：草稿的 LLM 呼叫不再擋在跌倒通知前面。
- **失敗不影響告警**：草稿產不出來只是表單空白，事件照常通報。
- **不必存**：草稿是可重算的衍生資料，不需要 DB 欄位，也不需要遷移。人工改過的內容存在通報單本身。

代價與待確認：

- 開表單時要等數秒。前端需顯示產生中狀態（P3.3 一併處理）。
- 「後端如何觸發 agent」與 Q7 是同一個問題（同進程 import vs 獨立服務），兩者應一起決定。

欄位以前端 `frontend/src/pages/ReportFormPage.tsx` 的表單 schema 為準（實作 P3 時先讀該檔對齊，此處不重複維護欄位清單以免兩處不同步）。原則：

- Agent 只填「客觀可推斷」欄位：時間、地點（location）、事件類型、現場描述（改寫自 vlm_summary）、建議處置。
- 涉及人身判斷的欄位（傷勢確認、送醫決定）一律留白給人工。
- 草稿必須標記 `"source": "ai_draft"`，前端據此顯示「AI 草稿，請核對」。

## 6. judge 節點 structured output（Agent 內部契約）

```python
class JudgeResult(BaseModel):
    verdict: Literal["true_alarm", "false_alarm", "uncertain"]
    confidence: float = Field(ge=0, le=1)
    reasoning: str                      # 繁中
```

（原本還有 `severity`，隨後端 2026-07-19 的清理一併移除；judge 不再需要產這個值，
`legacy_severity()` 那條退路也跟著刪了。）

解析失敗或重試耗盡 → 對外一律降級為 `ai_verdict=null`（交回人工），不丟例外中斷 consumer。

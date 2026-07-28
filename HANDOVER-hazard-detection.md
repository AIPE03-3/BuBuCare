# 交接紀錄：潛在危險物品偵測（hazard）

分支：`feat/hazard-detection`（從 `test/main-integration` 切出）
範圍：讓 rt_detr 偵測到危險物品時產生事件，顯示到前端既有的「潛在危險」頁。

---

## 一句話

rt_detr 看到 **刀（knife）／剪刀（scissors）** 時，推一則 `event_type="hazard"` 的事件
到前端「潛在危險」分頁。

前端的殼本來就都在（分頁、詳情頁、歷史「已排除危險」頁），缺的是 rt_detr 的偵測結果
**從來不外發** —— `detected_objects` 這個變數蒐集完就丟，不進 payload、不進 Kafka。
本次補上整條管線。

---

## 兩個 commit

```
f9d8937 chore(ai): 清掉 rt_detr 兩處死碼與誤導註解
16cc279 feat: 潛在危險物品偵測（knife/scissors）打通 AI → 後端 → 前端
```

**第一個是純刪除、行為零影響**，可以獨立 review 或單獨 revert：

| 死碼 | 為什麼是死的 |
|---|---|
| `detected_objects` | 建立後全檔沒有任何消費者 |
| mask 疊圖區塊（20 行） | 條件是 `masks is not None`，但 `triton_detr_client._postprocess` 恆回 `masks=None`（RT-DETR 沒有分割頭）→ 從來沒執行過 |

那段疊圖是 YOLO-Seg 換成 RT-DETR 時留下的殘跡，註解甚至還寫著「YOLO-Seg 的彩色半透明
不規則輪廓」。順帶修了三處跟著失準的註解。

---

## 動了哪些檔案

| 檔案 | 改動 |
|---|---|
| `ai/inference_test.py` | 危險物品狀態機、`build_hazard_payload()`、抽出兩個 helper |
| `ai/triton_detr_client.py` | 只改一行註解（`masks=None` 的說明） |
| `backend/core/models.py` | 新增 `hazard_object` 欄位；`clip_path` 改 nullable |
| `backend/events/router.py` | `EventCreateRequest` 兩欄調整、新例外納入 400 |
| `backend/events/service.py` | `MissingClipPathError`、clip_path 業務規則、序列化加欄位 |
| `backend/tests/test_events_post.py` | 改 1 支既有測試、新增 2 支 |
| `frontend/src/types/index.ts` | `HazardObject` 改英文 key + `HAZARD_OBJECT_LABEL` |
| `frontend/src/api/events.ts` | 拿掉「欄位未定」註解 |
| `frontend/src/components/HazardList.tsx`<br>`frontend/src/pages/HazardDetail.tsx`<br>`frontend/src/pages/Home.tsx` | 顯示改走 label 對照表 |
| `agent/schemas.py` | 只改 docstring（見下方「不影響 agent」） |
| `.env.example` | 新增 3 個 `HAZARD_*` 設定說明 |

---

## ⚠️ 合併後必做：DB migration

專案沒有 alembic，`init_db.py` 的 `create_all` **只建新表、不會幫既有表加欄位**。
測試全綠是因為測試用 SQLite 每次重建；**正式 PostgreSQL 沒跑這兩行，寫入 hazard 事件會炸**：

```sql
ALTER TABLE detect_events ADD COLUMN hazard_object VARCHAR(50);
ALTER TABLE detect_events ALTER COLUMN clip_path DROP NOT NULL;
```

（比照 `backend/docs/superpowers/plans/2026-07-07-sse-delivery-ack.md:79` 的既有慣例。）

---

## 契約變更（三條，都是本次的重點）

### 1. `clip_path` 從必填改選填

**為什麼**：潛在危險是「桌上有把刀」這種**持續狀態**，沒有「事發前後 N 秒」可錄，只有快照。
跌倒是瞬間事件才錄得到 clip。

**向後相容**：原本有帶 clip_path 的呼叫端一行都不用改。這是放寬不是收緊。

**但業務規則沒放生** —— Pydantic 層放行，service 層擋：

```python
# backend/events/service.py
_CLIPLESS_EVENT_TYPES = {"hazard"}   # 唯一允許不帶 clip_path 的事件類型

if data.get("event_type") not in _CLIPLESS_EVENT_TYPES and not data.get("clip_path"):
    raise MissingClipPathError(...)   # router 轉 400
```

`fall` / `chair_slip` 漏帶 clip_path 仍然當場 400，不會靜默寫進 DB。

**曾考慮但否決的做法**：塞快照路徑或空字串充數。那會讓 `core/s3.py` 的 presigned URL
換發把一張 jpg 當影片丟給前端，錯誤延後到使用者點播放才爆。

### 2. `detect_events` 新增 `hazard_object`

存 **COCO class name 原字串**（`"knife"` / `"scissors"`），跌倒事件為 `NULL`。

不做 Enum：值域會隨模型重訓長出新類別，不該每次都動 DB 型別。

### 3. 前端 `HazardObject` 從中文字面值改英文 key

```ts
// 改前：export type HazardObject = '刀具' | '熱源' | '藥品' | '玻璃碎片' | '積水' | '其他';
// 改後：
export type HazardObject = 'knife' | 'scissors';
export const HAZARD_OBJECT_LABEL: Record<HazardObject, string> = {
  knife: '刀具',
  scissors: '剪刀',
};
```

兩個理由：

1. **對齊專案既有慣例** —— `STATUS_LABEL` / `EVENT_TYPE_LABEL` 都是英文 key + 中文 label，
   且 `types/index.ts` 明文寫「顯示文字一律走對照表，元件外禁止另寫死」。
   三層（AI／後端／前端）傳同一個 key，中間不做語意轉換。
2. **清單收斂成模型真的認得的類別** —— 原清單是照情境想像列的：藥品／玻璃碎片／積水
   **不在 COCO 80 類**，`rtdetr-l.pt` 的權重裡根本沒有這些概念。留著只會變成永不觸發的
   死選項（同 `wheelchair` 的處境，見 `triton_detr_client.py` 檔頭）。

> ⚠️ 這是前端 breaking change，但使用點只有 4 處，都已改完（`tsc --noEmit` 通過）。
> `Home.tsx:65` 原本直接印 `entry.hazardObject` 原字串，沒改的話英文會漏到畫面上。

---

## 資料流

```
rt_detr (Triton)
   │
   └─→ results_env ──→ 危險物品狀態機（只在 detr 真的更新的幀推進）
                          │
                          └─ 確認成立 → build_hazard_payload()
                                          │
                        Kafka: processed-reports（不走 VLM 二審）
                                          │
                        backend/kafka_consumer.py（原樣轉發整包 dict）
                                          │
                                    POST /events
                                          │
                        DB 落庫 + SSE 廣播 event_created
                                          │
                        前端 EventsProvider：event_type === 'hazard' 分流
                                          │
                        ├─ 事件中心「潛在危險」分頁（status !== resolved）
                        ├─ /hazards/:id 詳情頁
                        └─ 歷史「已排除危險」（status === resolved）
```

**不走 VLM 二審**：物件偵測是「畫面裡有沒有這個東西」的明確判斷，不像跌倒需要 VLM 讀情境
（是真跌倒還是自己蹲下）。送二審只會多一層延遲跟成本，換不到任何額外資訊。

---

## 去重狀態機（本次最核心的設計）

### 為什麼不能沿用跌倒那套

| | 跌倒 | 危險物品 |
|---|---|---|
| 事件形狀 | 瞬間 | 持續狀態 |
| 每幀行為 | 觸發一次就結束 | **每一幀都偵測得到** |
| 現有去重 | `vlm_triggered` 一次性閂鎖，**永不重置** | 不適用 |

直接 `if knife: send()` → 30 FPS × 每秒 30 筆灌爆 Kafka 和前端。
套 `vlm_triggered` 那套 → 「一輩子只報第一把刀」，刀被收走再放一把新的就永遠不報了。

### 狀態機

```python
_hazard_state = {"knife": {"streak": 3, "missing": 0, "reported": False}}
# 每支相機 worker 各自一份（A 房的刀跟 B 房的刀是兩回事）

這輪沒看到 → missing += 1 → 滿 HAZARD_GONE_FRAMES 就刪整筆
                             （刪除＝忘記報過 → 物品再出現可重新告警）
這輪有看到 → streak += 1 → 滿 HAZARD_CONFIRM_FRAMES 且未報過 → 發一則，reported = True
```

### 參數（都可寫進 `.env`，見 `.env.example`）

| 參數 | 預設 | 作用 |
|---|---|---|
| `HAZARD_CONF` | 0.5 | 信心門檻。比環境家具的 0.35 嚴：誤報是直接吵護理師 |
| `HAZARD_CONFIRM_FRAMES` | 5 | 連續看到 N 次才確認，防單幀閃爍誤報 |
| `HAZARD_GONE_FRAMES` | 30 | 連續 M 次沒看到才判定移除，防遮擋抖動就誤判消失 |

> 這三個值是憑「防閃爍 + 防遮擋」估的，**沒有實測依據**。建議實際拿把剪刀進出鏡頭跑一輪
> 再調。三個都走 `cfg()` 讀 `.env`，不用改程式碼。

### ⚠️ 一個容易踩的細節

狀態機**只在 `_detr_updated` 為真的幀推進**。降頻（`DETR_EVERY_N > 1`）時 `results_env`
是**復用上一次的快取**，若每幀都算，`streak` 會用同一批偵測結果灌水，`CONFIRM_FRAMES`
就形同虛設。改這段的人請保留這個 guard。

---

## 不影響 agent

hazard 由 AI 端**直接**送 `processed-reports`，不經 agent／vlm_worker。
`agent/schemas.py` 只改了 docstring，加註一件事：

> `processed-reports` 現在有**兩種訊息形狀** —— agent 產的（`ProcessedReport`，clip_path 必填）
> 和 AI 端 hazard 產的（clip_path 為 None、多一個 hazard_object）。
> `backend/kafka_consumer.py` 原樣轉發不驗 schema，故兩種並存沒問題；
> 但別把 `ProcessedReport` 當成該 topic 的全集。

agent 測試 172 passed，未受影響。

---

## 驗證方式

```bash
# 後端（146 passed，新增 2 支）
cd backend && uv run pytest tests -q

# agent（172 passed）
cd agent && uv run pytest tests -q

# 前端
cd frontend && npm run build && npm run lint

# 契約護欄（278 檔）
python3 scripts/check_guardrails.py
```

新增的兩支測試：

- `test_跌倒缺clip_path_400` —— 跌倒漏帶影片仍被擋下
- `test_hazard缺clip_path_201` —— hazard 可以沒有影片

原本的 `test_缺必填欄位_422` 改驗 `detected_at`（仍是必填），沒有降低覆蓋率。

### 手動驗收

1. 拿把剪刀進鏡頭 → 前端「潛在危險」分頁出現一筆，物品欄顯示「剪刀」
2. 剪刀持續在畫面中 → **只有那一筆**，不會洗版
3. 把剪刀移走再放回 → 可以再次觸發

---

## 已知限制 / 明確不做

| 項目 | 理由 |
|---|---|
| 藥品／玻璃碎片／積水 | 不在 COCO 80 類，需重訓模型。建議跟 `wheelchair` 合併成一次 N 類重訓 |
| 熱源家電（oven/toaster/microwave） | 固定家電只要在畫面裡就永遠偵測得到 → 會變成**永久亮著的告警**。要做得先設計區域白名單或時段規則 |
| `wine glass`（玻璃器皿） | COCO 有，但交誼廳／餐廳正常會有杯子，誤報率過高 |
| hazard 錄影片 | 持續狀態沒有「事發前後」可錄，快照足夠 |
| hazard 走 VLM 二審 | 明確的有／無判斷，不需情境判讀 |

另外，前端「潛在危險」的**排除動作**（`EventsProvider` 的 `clearHazard`）目前仍是
**前端記憶體操作**，後端沒有對應端點，重整會歸零。這是本次之前就存在的落差，不在本次範圍。

---

## 合併注意

- 兩個 commit 可分開 cherry-pick：`f9d8937`（死碼清理）與功能無耦合。
- 可能衝突點：`ai/inference_test.py` 的 `camera_worker` 迴圈（本次在 detr 分支後插入狀態機
  區塊，並把跌倒觸發段的 device_id 解析與快照存檔改呼叫新抽出的 helper）。
- `backend/core/models.py` 的 `DetectEvent` 動了兩處（clip_path、新欄位）。
- **合併後別忘了跑上面那兩行 SQL。**

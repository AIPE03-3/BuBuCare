# CLAUDE.md — 本專案每次動工前必讀

長照跌倒偵測系統。邊緣端（`ai/`）用 Triton 跑三顆模型偵測跌倒 → Kafka → 後端
（`backend/`，FastAPI + PostgreSQL）→ 前端（`frontend/`）。低信心事件走 VLM 二審
（`ai/vlm_worker.py` + `ai/uncertainty_router.py`）。

**先讀這兩份再動手**：

- [`CONTRIBUTING.md`](CONTRIBUTING.md) — 兩台開發機（Linux/macOS）的協作規矩、護欄、分支流程
- [`NEXT_STAGE.md`](NEXT_STAGE.md) — 目前的待辦與各項狀態

---

## 一、`ai/modules/` 物件偵測模組白名單（硬規則）

**`ai/modules/` 底下只准存在、也只准 import 這兩個檔：**

| 檔案 | 用途 |
|---|---|
| `ai/modules/__init__.py` | 空檔，package marker |
| `ai/modules/sanity_check.py` | 模組 G：VLM 閒置算力環境安全巡檢 |

**除此之外一律不准**：不准新增檔案、不准把已刪的模組復活、不准 import、
相關功能與邏輯一律不套用。做這項任務或任何相關任務時，只會用到這兩個檔。

### 為什麼

2026-07-27 刪掉了原本的五個模組：`bed_exit.py`（A 離床）、`wandering.py`（E 遊走）、
`micro_motion.py`（F 躁動）、`audio_fusion.py`（H 音訊融合）、`chair_slip.py`（I 座椅滑落）。

1. **前三個都繞過契約自己送 Kafka**。它們各自組一份 payload 直接
   `producer.send('processed-reports', ...)`，欄位對不上後端的 `EventCreateRequest`
   （多了 `alert_id`/`camera_id`/`status`，少了 `clip_path`/`snapshot_path`），
   **每一則都被後端 422 退件**。用 `test4.mp4` 跑完整管線時實測確認，後端 log 是
   `POST /events HTTP/1.1" 422 Unprocessable Entity` + `ERROR 毒訊息，跳過`。
2. **`audio_fusion.py` 是展示用的假資料產生器**，不是偵測能力。它對 camera_id 含 `"303"`
   的相機**每 22 秒隨機**丟出 `THUD_CRASH`/`HELP_SCREAM`，並把信心強制拉到 `0.96` 直入
   快速道。刪掉它是移除一個誤報來源。
3. **本階段只保留跌倒機制。**

### 跌倒主邏輯不在 `modules/` 裡

跌倒判定一直都在 [`ai/inference_test.py`](ai/inference_test.py) 的 `camera_worker`
主迴圈：防線 A（肩髖體角 + 長寬比判定臥倒）、防線 B（幾何遮擋防禦）、
AcT 時序分類（30 幀視窗 → Triton `action_transformer`）。所以上面那一刀不影響跌倒偵測。

### 這條規則是機器在擋，不是只寫在這裡

[`scripts/check_guardrails.py`](scripts/check_guardrails.py) 的 `check_module_whitelist()`
會擋下兩種違規：在 `ai/modules/` 新增非白名單檔案、以及任何 `.py` 去 import 非白名單模組。
pre-commit 與 GitHub Actions 兩層都會紅燈。

### 真的要復活某個模組時

三件事缺一不可，**不要只改護欄讓它過**：

1. 改本檔的白名單表，寫清楚為什麼要收回這個決定
2. 改 `scripts/check_guardrails.py` 的 `MODULES_ALLOW`
3. **先補契約測試**：確認該模組不會自組 payload 外發，外發一律回主迴圈的
   `route_by_confidence()`（範本是已刪除的 `chair_slip.py` 的做法：模組只偵測、回傳訊號）

---

## 二、契約邊界（動到要先跟後端組講好）

- **Kafka topic 名稱**：`processed-reports`、`nursing-home-alerts`
- **`route_by_confidence()` 的 payload 欄位**（`ai/inference_test.py`）——護欄 AST 檢查會擋。
  護欄看的是 payload dict 的 **keys**，函式簽章與欄位的值不在檢查範圍。
- **`event_type` 目前值域**：`"fall"`（快速道/二審）與 `"Routine_Environment_Sanity_Check"`
  （巡檢）。後端與 agent 都當字串處理，不是 enum。

## 三、AWS 憑證分工（兩組金鑰，不要混用）

| 金鑰 | 誰在用 | 權限 |
|---|---|---|
| `S3_RW_REGION` / `S3_RW_ACCESS_KEY_ID` / `S3_RW_SECRET_ACCESS_KEY` | `ai/inference_test.py` 上傳事件片段 | 讀寫（`PutObject`）|
| `S3_REGION` / `ACCESS_KEY_ID` / `SECRET_ACCESS_KEY` | `backend/core/s3.py` 簽 presigned URL | 唯讀（`GetObject`）|

刻意分開＝最小權限。**不要把讀寫金鑰塞進後端那三個名字**，那會讓後端也拿到寫入權限。

## 四、其他必記

- **不要直接 push `test/main-integration`**；開自己的分支 → PR → 在 5060 Ti 那台驗過再合。
- **路徑不要寫死家目錄**（`/home/xxx/`、`/Users/xxx/`），用 `__file__` 基準或環境變數。
- **Triton 的 HTTP 埠實際掛 8010**（8000 被 backend 佔），gRPC 8011、metrics 8002。
- AI 端的設定一律讀 **repo 根目錄的 `.env`**（`ai/backend_devices.py` 的 `cfg()`）。
  `ai/.env` 只有 ClearML 那支腳本在讀，放在那裡的設定 `inference_test.py` 看不到。

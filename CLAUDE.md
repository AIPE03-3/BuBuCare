# CLAUDE.md — 本專案每次動工前必讀

長照跌倒偵測系統。邊緣端（`ai/`）用 Triton 跑三顆模型偵測跌倒 → Kafka → 後端
（`backend/`，FastAPI + PostgreSQL）→ 前端（`frontend/`）。低信心事件走 VLM 二審
（`ai/vlm_worker.py` + `ai/uncertainty_router.py`）。

**先讀這兩份再動手**：

- [`CONTRIBUTING.md`](CONTRIBUTING.md) — 兩台開發機（Linux/macOS）的協作規矩、護欄、分支流程
- [`NEXT_STAGE.md`](NEXT_STAGE.md) — **還沒做完的**：待辦與各項狀態

**不熟悉整個系統的話先看** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — 架構全貌、
資料怎麼流、為什麼這樣設計，以及**現況與規劃的差距**（第六節：哪些是已知未修的缺陷、
哪些元件沒被驗證過、哪些文件已過時）。

**要查「某件事當初為什麼那樣做」** → [`docs/CHANGELOG-STAGES.md`](docs/CHANGELOG-STAGES.md)。
已完成階段的紀錄都在那裡（含各項踩過的坑、以及為什麼當時的測法測不出來）。
Mac 本機環境的建置任務表在 [`docs/MAC_SETUP_WBS.md`](docs/MAC_SETUP_WBS.md)，
操作手冊在 [`RUN_ON_MAC.md`](RUN_ON_MAC.md)。

---

## 一、`ai/modules/` 物件偵測模組白名單（硬規則）

**`ai/modules/` 底下只准存在、也只准 import 這四個檔：**

| 檔案 | 用途 | 狀態 |
|---|---|---|
| `ai/modules/__init__.py` | 空檔，package marker | — |
| `ai/modules/sanity_check.py` | 模組 G：VLM 閒置算力環境安全巡檢 | 在用 |
| `ai/modules/bed_exit.py` | 模組 A：離床偵測 | **2026-07-30 放行研究，需先修契約**（見下）|
| `ai/modules/chair_slip.py` | 模組 I：座椅滑落 | **2026-07-30 放行研究**，契約本來就乾淨 |

**除此之外一律不准**：不准新增其他檔案、不准把 `wandering.py`（E 遊走）、
`micro_motion.py`（F 躁動）、`audio_fusion.py`（H 音訊融合）復活、不准 import 它們。

### 2026-07-30：收回「離床」與「座椅滑落」的封印

**決定**：這兩項功能要拿回來做，所以放行進白名單供研究與開發。
其餘三個（遊走、躁動、音訊融合）維持封印。

**檔案怎麼取回**（檔案本身不在版控中，要從歷史撈）：

```bash
git show 61c9f63^:ai/modules/bed_exit.py   > ai/modules/bed_exit.py
git show 61c9f63^:ai/modules/chair_slip.py > ai/modules/chair_slip.py
```

`61c9f63` 是當初刪除那五個模組的 commit，`^` 表示它的前一顆（還有檔案的那個版本）。

**⚠️ 兩個檔的狀況完全不同，動工前一定要知道**：

| | `chair_slip.py`（座椅滑落）| `bed_exit.py`（離床）|
|---|---|---|
| 契約行為 | ✅ **乾淨**：只 `return True/False` | ❌ **違約**：第 52 行 `producer.send('processed-reports', ...)` |
| 復活後 | 直接可用，護欄會過 | **護欄會擋下來**，必須先改 |
| 說明 | 早期版本曾自組 payload，已於 `d20f68c` 修掉（檔內註解有記）| payload 多 `alert_id`/`camera_id`/`severity`/`status`，少 `clip_path`/`snapshot_path` → 後端 422 |

**`bed_exit.py` 要怎麼改才能過**：把 `producer.send(...)` / `producer.flush()` 整段拿掉，
改成只 `return is_leaving_bed`，讓主迴圈的 `route_by_confidence()` 統一組 payload 外發。
**照 `chair_slip.py` 的樣子做就對了**，它就是這個範本。

### 為什麼當初要封印（背景，仍然適用）

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

[`scripts/check_guardrails.py`](scripts/check_guardrails.py) 有兩道檢查，
pre-commit 與 GitHub Actions 兩層都會紅燈：

| 檢查 | 擋什麼 |
|---|---|
| `check_module_whitelist()` | 在 `ai/modules/` 新增**非白名單**檔案、以及任何 `.py` 去 import 非白名單模組 |
| `check_module_no_kafka()` | `ai/modules/` 底下的檔案**自己送 Kafka**（任何 `.send(...)` 呼叫）；快速道 `processed-reports` 一律擋，慢速道只放行 `sanity_check.py` |

**第二道是重點**。白名單管的是「哪些檔可以存在」，那是會隨階段決策變動的；
真正不能退讓的是「模組不准自組 payload 外發」——那才是當初被後端 422 靜默丟棄的根因。
所以 2026-07-30 放寬白名單時，同時補上了這道檢查：**白名單可以放，契約不能放。**

它認的是方法名 `.send()` 而不是變數名，所以 `self.producer.send()`、
`kafka_producer.send()` 這些改寫法都躲不掉。topic 寫成變數或 f-string 也躲不掉——
判不出是哪一道就**當快速道處理**（寧可誤擋，放過就是 422 靜默丟棄）。

**唯一的例外是 `sanity_check.py`**（列在 `MODULES_SLOW_LANE_OK`）。它送的是**慢速道**
`nursing-home-alerts`，收件人是 `vlm_worker`／agent，都是 AI 內部；二審端會重組 payload
才進 `processed-reports`，所以不受契約欄位約束，實測一直是好的
（`event_type` = `Routine_Environment_Sanity_Check`）。它是設計上就要自己截圖外發榨 VLM
閒置算力，主迴圈沒有對應的巡檢分支可以接手。

**不要拿它當前例**。要再往 `MODULES_SLOW_LANE_OK` 加人，先問「這個能不能回主迴圈的
`route_by_confidence()`」——能就不該加。真有單行要放行，該行尾加 `# guardrail: allow`
（但先想清楚是「規則不適用」還是「這次先過」——後者不該豁免）。

### 真的要復活某個模組時

三件事缺一不可，**不要只改護欄讓它過**：

1. 改本檔的白名單表，寫清楚為什麼要收回這個決定
2. 改 `scripts/check_guardrails.py` 的 `MODULES_ALLOW`
3. **確認該模組不會自組 payload 外發**，外發一律回主迴圈的 `route_by_confidence()`
   （範本是 `chair_slip.py` 的做法：模組只偵測、回傳訊號）
   —— 這項現在由 `check_module_no_kafka()` 機器強制，但**不要因為有機器擋就不看**：
   護欄只擋 Kafka 外發，不會幫你檢查偵測邏輯對不對、或事件會不會誤報。

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

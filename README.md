# 長照跌倒偵測系統

資策會 AIPE03 第三組。攝影機畫面進來 → AI 判斷有沒有人跌倒 → 通知護理站 → 留下影片證據
供人工複判 → 複判結果回頭餵給模型重訓。

```
攝影機/mp4 ─→ MediaMTX ─→ ai/（Triton 三顆模型）─→ Kafka ─→ backend/ ─→ frontend/
                                     │                        （FastAPI）   （React）
                              低信心的走二審 ──→ VLM
                                     │
                              事件樣本 ──→ Label Studio ──→ ClearML 重訓 ──→ Triton 熱載
```

**這份只是路標。** 要理解系統怎麼運作，看 **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)**。

---

## 目錄結構

| 目錄 | 負責什麼 |
|---|---|
| [`ai/`](ai/) | 邊緣端推論。Triton 跑 `yolo_pose` / `rt_detr` / `action_transformer` 三顆模型判定跌倒，事件發進 Kafka；MLOps 重訓迴路也在這 |
| [`backend/`](backend/) | FastAPI + PostgreSQL(AWS RDS)。消費 Kafka 落 DB、SSE 推前端、簽 S3 presigned URL |
| [`frontend/`](frontend/) | React 19 + Tailwind 4。事件中心、即時監控、通報單、歷史查詢 |
| [`agent/`](agent/) | LangGraph 版二審（7 節點）。**目前 shadow 模式**，正式服務的仍是 `ai/vlm_worker.py` |
| [`streaming/`](streaming/) | MediaMTX 設定與串流說明 |
| [`scripts/`](scripts/) | 護欄檢查、環境自檢 |
| [`gcp_vm_environment/`](gcp_vm_environment/) | 雲端 VM 的部署設定（與主 stack 是兩套架構，導入時要搬零件不要並存） |
| [`docs/`](docs/) | 全部文件，見下 |

---

## 先讀哪一份

| 你想做什麼 | 看這份 |
|---|---|
| **動手改任何東西之前** | [`CLAUDE.md`](CLAUDE.md) —— 硬規則（模組白名單、契約邊界、金鑰分工），機器會擋 |
| 理解整個系統 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) —— 資料怎麼流、為什麼這樣設計 |
| **知道哪裡還是壞的** | 同上第六節「現況與規劃的差距」 |
| 把系統跑起來（Linux/一般） | [`docs/DEPLOY.md`](docs/DEPLOY.md) |
| 把系統跑起來（macOS） | [`docs/RUN_ON_MAC.md`](docs/RUN_ON_MAC.md) |
| 協作規矩、分支流程 | [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) |
| 還有什麼沒做完 | [`docs/NEXT_STAGE.md`](docs/NEXT_STAGE.md) |
| 某件事當初為什麼那樣做 | [`docs/CHANGELOG-STAGES.md`](docs/CHANGELOG-STAGES.md) |

`backend/` `frontend/` `agent/` 各自的 `docs/` 有該層更細的設計文件。

---

## 最快跑起來

```bash
cp .env.example .env      # 填好裡面的憑證，不填會被 docker compose 直接擋下來
docker compose up -d      # kafka / kafka-ui / backend / frontend
```

前端 <http://localhost>、後端 <http://localhost:8000/docs>。

AI 推論不在這包（要 Triton + 模型權重），照 [`docs/DEPLOY.md`](docs/DEPLOY.md) 或
[`docs/RUN_ON_MAC.md`](docs/RUN_ON_MAC.md) 走。

> **⚠️ Triton 的 HTTP 埠是 8010 不是 8000** —— 8000 被 backend 佔了。
> 沒設 `TRITON_*_URL` 的話推論會打到 FastAPI 拿 404 然後**靜默降級**：
> 畫面照跑、FPS 照印、零紅字，但姿態偵測全程失效。

---

## 動工前一定要知道的三件事

1. **`ai/modules/` 有白名單，而且是機器在擋。** 模組只能回傳訊號，
   **不准自己送 Kafka** —— 曾經三個模組各自組 payload 外發，欄位對不上被後端 422
   靜默丟棄，跑短影片測不出來。規則與理由在 [`CLAUDE.md`](CLAUDE.md) 第一節。

2. **兩組 S3 金鑰刻意分開。** AI 端上傳用 `S3_RW_*`（讀寫），後端簽網址用
   `S3_REGION`/`ACCESS_KEY_ID`/`SECRET_ACCESS_KEY`（唯讀）。
   **不要把讀寫金鑰塞進後端那三個名字。**

3. **不要直接 push `test/main-integration`。** 開自己的分支 → PR → 在有 GPU 的機器驗過再合。

送出前跑一次護欄（pre-commit 與 CI 也都會跑）：

```bash
python3 scripts/check_guardrails.py
```

---

## ⚠️ 這個系統還沒有生產就緒

跌倒偵測在**俯視鏡頭**下的幾何判定是失效的（站著的人軀幹投影就接近水平，
與臥倒特徵相同，調門檻無效），而正式環境正是公共區域俯視。
MLOps 迴路目前是**半自動**，有幾支元件從未被驗證過。

不要照前面幾節的樂觀描述估算成熟度 ——
完整清單在 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 第六節，那節是刻意寫最詳細的。

# 交接紀錄：事件片段存檔（NEXT_STAGE 第 2 項）

分支：`test/main-integration`
範圍：只做 NEXT_STAGE 第 2 項。**第 1 項（冷卻計時器）刻意沒做**，理由見文末。

---

## 一句話

跌倒觸發時，把該瞬間**前 5 秒 + 後 5 秒**的畫面寫成一支獨立 mp4，Kafka payload 的
`clip_path` 從「影像來源本身」改指向這支片段。

以前 `clip_path` 塞的是 `video_source`：影片檔時代那就是那支 mp4 還說得過去，接上
RTSP 之後會變成一個 `rtsp://` 網址 —— 前端點下去根本沒有事發當時的畫面可看。

---

## 動了哪些檔案

| 檔案 | 改動 |
|---|---|
| `ai/inference_test.py` | 片段緩衝、寫檔、S3 選配上傳（+166 行） |
| `.env.example` | 新增 5 個 `CLIP_*` 環境變數說明 |
| `.gitignore` | 加 `ai/clips/`（執行時產物） |

**後端契約完全沒動**：`route_by_confidence()` 兩個 payload 的欄位一個字沒改，
`scripts/check_guardrails.py` 的 AST 檢查通過。只把函式的關鍵字參數
`video_source=` 改名成 `clip_path=`（[:63](ai/inference_test.py#L63)），
欄位名 `clip_path` 是契約邊界、只換了裡面放的值。

---

## 程式碼位置

### 模組層（`ai/inference_test.py`）

| 位置 | 內容 |
|---|---|
| [:116-138](ai/inference_test.py#L116) | `CLIP_*` 環境變數與預設值 |
| [:141](ai/inference_test.py#L141) | `_downscale_for_clip()` —— 緩衝幀等比降寬 |
| [:153](ai/inference_test.py#L153) | `_video_fourcc()` —— OpenCV 4.x / 5.x API 適配 |
| [:163](ai/inference_test.py#L163) | `write_event_clip()` —— 寫 mp4 +（選配）上傳 S3 |

### `camera_worker` 內（[:247](ai/inference_test.py#L247)）

| 位置 | 內容 |
|---|---|
| [:293](ai/inference_test.py#L293) | 緩衝初始化：`pre_clip_buffer` / `post_clip_buffer` / 旗標 |
| [:414](ai/inference_test.py#L414) | 每幀塞緩衝、後段收滿即丟背景執行緒寫檔 |
| [:670](ai/inference_test.py#L670) | 觸發時算路徑、拍前段快照、開始錄後段 |
| [:363](ai/inference_test.py#L363) | 斷線重連：依新 fps 重算幀數、中止進行中的錄影 |
| [:392](ai/inference_test.py#L392) | 影片檔播完的收尾補寫 |

---

## 環境變數（全部可不設）

| 變數 | 預設 | 說明 |
|---|---|---|
| `CLIP_PRE_SEC` | `5` | 觸發前保留幾秒 |
| `CLIP_POST_SEC` | `5` | 觸發後續錄幾秒 |
| `CLIP_WIDTH` | `640` | 緩衝幀降寬省記憶體。`0` = 不縮 |
| `CLIP_DIR` | `ai/clips` | 片段輸出目錄 |
| `CLIP_S3_BUCKET` | 未設 | **設了才上傳**，見下方「已知限制」 |
| `CLIP_S3_PREFIX` | `videos` | S3 key 前綴 |

---

## 設計決策與理由

### 1. 緩衝存「原始幀」，位置在跳幀之前

我們的 worker 有 `frame_count % 2` 隔幀跳過。緩衝若擺在跳幀之後，5 秒只會收到
2.5 秒份量的畫面，寫出來的片段時間軸整個對不上。故緩衝擺在 `cap.read()` 成功後、
跳幀判斷之前。

### 2. 片段不畫 AI 標註框

存乾淨原始畫面。理由：不受 `NO_RENDER=1` 影響（headless 壓測下行為一致）、
不必為每個緩衝幀多跑一次 `.plot()`；而且被跳過的幀根本沒有推論結果可畫，
硬要畫會錄出一閃一閃不連續的框。

### 3. 警報立刻發，片段稍後落地

觸發當下就把路徑算好、隨 payload 發出 Kafka；後段錄滿才在背景執行緒寫檔。
跌倒是急救場景，為了等影片而讓警報延遲 5 秒以上不划算。護理師從收到警報到
點開影片本來就不只 5 秒，屆時檔案早已落地。

（albert 分支選的是相反做法「等影片寫完才發警報」。）

### 4. 用 `cv2.VideoWriter`，不用 ffmpeg pipe

NEXT_STAGE 寫「albert `:463` 用 ffmpeg pipe 寫檔」，實際去看 albert 分支，
片段寫檔用的是 `cv2.VideoWriter`（`avc1` → `mp4v` 退版）；ffmpeg pipe 是另一段
RTSP 推流、與片段無關，而且寫死 `h264_videotoolbox`（**Mac 專屬編碼器**）。

`cv2.VideoWriter` 跟著 `opencv-python` 走，不需要外部 ffmpeg 執行檔，
Windows / macOS / Linux 都能跑。

### 5. Windows 相容性（另一台開發機是 Windows）

- `fourcc` 做了版本適配：OpenCV 4.x 是 `cv2.VideoWriter_fourcc`，
  5.x 移到 `cv2.VideoWriter.fourcc`。寫死任一邊會在另一台 `AttributeError`。
- 路徑全走 `os.path.join`，無絕對路徑；護欄檢查（278 檔）通過。
- `boto3` 是 lazy import：沒設 `CLIP_S3_BUCKET` 的機器不必裝 boto3、不必有 AWS 憑證。

### 6. 記憶體

1080p 全解析度下，前後 10 秒每台相機約要 1.8GB，多路併發直接 OOM。
故片段緩衝**獨立降寬**到 `CLIP_WIDTH`（推論吃的仍是原圖，完全不受影響），
且後段寫完立刻斷開參照釋放。

---

## ⚠️ 沒有照抄 albert：他的實作有 bug

albert 的 `pre_video_buffer` 每幀都在滾動，但**收工當下才去取它**：

```python
full_10_sec_frames = list(pre_video_buffer) + post_video_buffer   # ← 這裡
```

等後段錄滿 5 秒，那個環形緩衝裡裝的已經正好是**後段那批幀**，拼出來是
「後 5 秒 ×2」，前 5 秒整段遺失。

本實作改成**觸發當下就對前段緩衝拍快照**（`pre_clip_snapshot = list(pre_clip_buffer)`），
收工時用快照拼接。模擬驗證（30fps、第 400 幀觸發、前後各 5 秒 = 150 幀）：

```
[本實作] 幀數=300 範圍=251..550 ✅ 時間軸正確
[albert] 幀數=300 範圍=401..550 ❌ 重複 150 幀，前半段是 401..550
```

---

## 驗證到什麼程度

**已驗證**
- `python3 -m py_compile ai/inference_test.py` 通過
- `python3 scripts/check_guardrails.py` 通過（278 個檔案，含 payload 契約 AST 檢查）
- AST 靜態檢查：兩個 payload 都是 `str(clip_path)`、函式內無未定義名稱
- 緩衝時間軸以純 Python 模擬驗證（見上一節）

**未驗證 —— 交接重點**
**沒有實際執行過整條管線。** 開發機的 venv 沒有 `cv2`，且真的要跑需要
Triton 三顆模型 + Kafka + 影像源。

最沒把握的是**編碼器那段**：`avc1` 能不能開、退 `mp4v` 的路徑對不對，
只有真的跑一次才知道。**請優先驗這個。**

### 建議的第一次測試

```bash
CAMERA_SOURCE=hardcoded SINGLE_SOURCE=ai/test_demo/test1.mp4 python ai/inference_test.py
```

檢查點：
1. 跌倒觸發後有沒有印出 `🎬 事件片段已寫入（N 幀 @ M fps）`
2. `ai/clips/` 底下的 mp4 打得開嗎、是不是約 10 秒
3. **前 5 秒是不是跌倒之前的畫面**（這是與 albert 版本的關鍵差異）
4. 若印出 `❌ 片段寫檔失敗：avc1 / mp4v 編碼器都開不起來` → 該機器的 OpenCV
   build 沒帶編碼器，要另尋方案

---

## 已知限制

### `clip_path` 目前是本地路徑，前端仍看不到影片

後端 `GET /events/{id}/media` 走 `backend/core/s3.py` 的 `generate_presigned_url()`，
它對**非 `s3://` 開頭的值一律回 `None`**（`backend/tests/test_event_media.py` 有
「舊本機路徑 → clip_url 給 null」的測試案例）。

`CLIP_S3_BUCKET` 沒設時，`clip_path` 塞的是本地路徑 → 前端拿到 null。

**要接通前端**：在 `.env` 補 `CLIP_S3_BUCKET=<bucket 名>`，並確保該機器有 AWS 憑證
（沿用後端那組 `S3_REGION` / AWS 標準憑證鏈），`clip_path` 就會變成 `s3://...`。

這樣設計的原因：沒有憑證的機器照樣跑得動、不會在跌倒當下噴錯，只是暫時沒影片。

### 每幀多一次 resize

`_downscale_for_clip()` 對每一幀（含被跳過的幀）都跑一次 `cv2.resize`。
1080p → 640 用 `INTER_AREA` 約 1ms 量級。這是環形緩衝的固有成本，
但**壓測 FPS 數字會比改動前略低**，量測時請留意。`CLIP_WIDTH=0` 可關掉縮放
（但記憶體自負）。

### 片段只會錄一次（因為冷卻沒做）

錄影的觸發點掛在既有的 `vlm_triggered` 一次性旗標下，所以**每個 worker 生命週期
只會錄一支片段**，與改動前「只發一次警報」的行為一致。做了冷卻之後這條才會跟著解開。

---

## 為什麼沒做 NEXT_STAGE 第 1 項（冷卻計時器）

設計討論中發現一件事：**這條管線分不出「同一個人」還是「另一個人」。**

`ai/inference_test.py` 每幀會用「信心度 × 框面積」挑出**最大的那一個人**，
只把這一個人的骨架餵給跌倒判斷。沒有人物編號、沒有身分追蹤。

所以任何以時間為基礎的冷卻，都存在這個漏洞：

```
0:00  A 跌倒         → 發警報 ✅
1:00  A 被扶起
2:00  B 跌倒          → 冷卻未過，不發 ❌
3:30  B 自己爬起來
5:00  地上沒人        → B 那筆從頭到尾沒發過，永久漏掉
```

會漏的是「發生在冷卻期間內、且在冷卻結束前就結束」的事件。冷卻越長漏得越多，
冷卻越短則無人處理的躺地者被重複催報越頻繁 —— 這是一個蹺蹺板，沒有免費解。

要真正解決需要**多人追蹤**（給每個人 ID、冷卻改成每人一份），
連帶要改 `best_idx` 選單一人的邏輯與餵給 AcT 的 30 幀視窗。
這是 NEXT_STAGE 沒提到的新功能，範圍不小，**故本次不做，留給接手者決定**。

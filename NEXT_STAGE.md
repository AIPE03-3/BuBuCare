# 下一階段待辦

階段 4（接真實 RTSP 攝影機）完成後浮出來的兩件事。兩件都跟「攝影機是 24 小時長跑」
這個新前提有關 —— 以前跑影片檔跑完就結束，所以都看不出來。

---

## 1. 跌倒事件只發一次：改成冷卻幾分鐘後可再發

**現況**：`ai/inference_test.py` 的 `vlm_triggered` 是 per-worker 的一次性旗標
（[ai/inference_test.py:206](ai/inference_test.py) 初始化、[:501](ai/inference_test.py) 判斷、
[:524](ai/inference_test.py) 設起來就永不清除）。同一路相機的 worker，**整個行程生命週期只會
發出一次跌倒事件**；`ever_detected_fall` 也會讓畫面永遠停在 "FALL DETECTED!"。

**為什麼以前沒事**：影片檔 worker 播完就結束、行程也跟著收工，一支影片本來就只該報一次。
接上真攝影機後 worker 會跑好幾天 —— 等於第一次跌倒之後，那台相機就再也不會示警了。

**要做什麼**：把「一次性閂鎖」換成「冷卻計時器」。同一起事件在冷卻時間內不重複發（避免
一次跌倒連發十筆），冷卻過了就恢復可發報。

**設計時要想清楚的**：
- 冷卻長度（暫定幾分鐘）要能用環境變數調，未設時給一個保守預設。
- 冷卻的粒度：是「每台相機一個冷卻」還是「每種事件類型一個冷卻」（跌倒 / 座椅滑落 /
  離床是不同防線，混在一起會互相蓋掉）。
- 斷線重連時**不要**重設冷卻（現在重連刻意保留 `ever_detected_fall` / `vlm_triggered`，
  就是為了避免網路抖動導致同一起事件重複發報 —— 換成計時器後要保持這個性質）。
- 不能動 Kafka 的 9 欄 payload 契約（`route_by_confidence` 受 `scripts/check_guardrails.py`
  的 AST 檢查監看）。

---

## 2. 跌倒瞬間前後各 5 秒的影片片段存檔

**現況**：Kafka payload 的 `clip_path` 現在塞的是**影像來源本身**
（[ai/inference_test.py:85](ai/inference_test.py) 與 [:100](ai/inference_test.py) 都是
`str(video_source)`）。影片檔時代這還說得過去（就是那支 mp4），但接上 RTSP 之後
`clip_path` 會變成一個 `rtsp://...` 網址 —— 前端點下去根本沒有「事發當時」的畫面可看。

**要做什麼**：跌倒觸發時，把該瞬間**前 5 秒 + 後 5 秒**（暫定，要可調）的影像存成一個片段，
`clip_path` 改指向這個片段。

**從 albert 分支抓現成的來改**：`origin/albert_chiang` 的
`Fall/tools/inference_test.py` 已經有完整實作，可直接參考：

| 位置 | 內容 |
|---|---|
| `:408-409` | `MAX_PRE_FRAMES = int(fps * PRE_SEC)` / `MAX_POST_FRAMES = int(fps * POST_SEC)` |
| `:412-415` | `pre_video_buffer = deque(maxlen=...)`（前段環形緩衝）＋ `post_video_buffer` list ＋ `is_recording_post` 旗標 |
| `:463` | 用 ffmpeg pipe（`-c:v libx264 -preset ultrafast`）寫檔 |
| `:484-500` | 每幀塞進 pre buffer；觸發後改塞 post buffer |
| `:767-768` | 觸發跌倒時 `is_recording_post = True`、`post_frame_count = 0` |

**搬過來要改的地方**（不能整段照抄）：
- albert 分支是 orphan、無共同歷史，且含歷史機密與 Mac 絕對路徑 —— **只抓邏輯，逐段重寫**，
  不要 cherry-pick、不要複製整支檔案。
- 我們的 worker 已經有隔幀跳過（`frame_count % 2`）與 `DETR_EVERY_N` 降頻，緩衝要存的是
  **原始幀**還是**已處理幀**要先想清楚（存原始幀才是真的 5 秒）。
- 目前 `NO_RENDER=1` 時整段畫圖是跳過的，片段裡要不要有標註框要決定。
- RTSP 是無限長跑：pre buffer 是 deque 有上限沒問題，但 post buffer 是 list，要確保
  錄完就清掉，否則記憶體會一路長。
- 片段存哪、怎麼給後端拿到（本地路徑 vs 上傳 S3）要跟後端對齊 —— `clip_path` 是 9 欄契約
  裡的欄位，**欄位本身不能改**，只能改裡面放什麼值，換內容前要先跟後端組講好。
- 重連後 fps 可能重新協商過，`MAX_PRE_FRAMES` 要跟著重算（`frame_delay` 已經有重算了）。

**跟第 1 項的關聯**：兩件事都在同一段觸發程式碼裡（`:501-524`），一起做比較省事 ——
冷卻計時器決定「這次要不要發」，片段存檔決定「發出去的 clip_path 指向什麼」。

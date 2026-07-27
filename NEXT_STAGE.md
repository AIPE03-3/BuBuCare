# 下一階段待辦

階段 4（接真實 RTSP 攝影機）完成後浮出來的兩件事。兩件都跟「攝影機是 24 小時長跑」
這個新前提有關 —— 以前跑影片檔跑完就結束，所以都看不出來。

各項標題前的【】標記目前狀態，一眼掃過去就知道要不要動：
【待辦】＝還沒做；【本輪不執行】＝已決定這輪不做（理由見該項）；
【已完成】＝驗證過了，不用重做。

---

## 待辦總覽：三條互不依賴、可分頭進行的工作

**① S3 權限確認**（外部行動，不是 code）
問後端組／AWS 管理者：`.env` 的 `ACCESS_KEY_ID` 對 `aipe03-3` bucket 有沒有
`PutObject` 權限。權限確認前**絕對不要設** `CLIP_S3_BUCKET`（見 `HANDOVER.md`「已知限制」，
設了但沒權限＝上傳失敗但已發出壞連結，比現在「誠實沒有」更難查）。

**② 三個模組契約破口修復**（code 工作，對應第 3 項）
`micro_motion.py` 已用實測證據確認會被後端 422 丟棄；`wandering.py`／`bed_exit.py`
程式碼型態相同，推測同款問題但未實測；`sanity_check.py` 走二審佇列，影響不同，待查。
修法範本在 `chair_slip.py:40-49`（stage2 已修過同款破口）。

**③ 事件冷卻計時器**（對應第 1 項，本輪已決定不執行）
卡在多人追蹤缺口——系統分不出同一人或另一人，加冷卻會永久漏接冷卻期間發生的
別人的跌倒。需要多人追蹤才能真正解決，範圍不小，這輪先接受現況限制。

以上三條互不依賴。另外 **agent P2**（後端記錄 AI 判斷＋前端顯示，見第 4 項）
也是獨立的一塊，可以跟上面三條同時分頭進行，不互相卡。

---

## 1.【本輪不執行】跌倒事件只發一次：改成冷卻幾分鐘後可再發

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

## 2.【已完成：片段錄製；S3 上傳待①權限確認】跌倒瞬間前後各 5 秒的影片片段存檔

> ✅ **片段錄製（前5秒＋後5秒＋mp4寫檔）已完成並實測驗證**——見 `HANDOVER.md`
> 交接紀錄與 `test-main-stage6-clip-s3` tag（編碼器fallback、前後切分邏輯、視覺比對、
> 9欄契約、S3未設時的降級行為，皆已用真實管線跑過驗證，不用重做）。
> ⏳ **唯一沒完成的是 S3 上傳本身**——卡在權限未確認（見 `HANDOVER.md`「已知限制」與待辦總覽①），
> `clip_path` 目前仍是本地路徑，前端還看不到影片。以下是原始需求記錄（保留供參考）：

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

---

## 3.【待辦，未修復】三個模組疑似跟 chair_slip 修復前同款契約破口（會被後端 422 丟棄）

**2026-07-27 用 `test4.mp4`（4.9 分鐘）第一次跑完整管線時發現**。之前所有測試影片都太短
（test1/2/3 僅 7.8~9.2 秒），跑不到這幾個模組的計時器門檻（15~22 秒起跳），所以這個破口
**一直沒被任何測試曝露過**。

**已用實測證據確認（不是推測）**：`ai/modules/micro_motion.py:45-58`（模組 F，夜間躁動）
在偵測到躁動時，繞過 `route_by_confidence()`，自己組一份 payload 直接
`producer.send('processed-reports', ...)`：

```python
agitation_payload = {
    "alert_id": f"AGT_{self.camera_id}_{int(time.time())}",   # ← 契約沒有這欄
    "device_id": numeric_id, "event_type": "agitation",
    "detected_at": ..., "camera_id": self.camera_id,          # ← 契約沒有這欄
    "yolo_score": ..., "vlm_summary": ..., "severity": "medium",
    "status": "UNREAD"                                         # ← 契約沒有這欄
    # 缺 clip_path / snapshot_path / yolo_threshold —— 9 欄契約少了 3 個必要欄位
}
```

後端 log 實測結果：

```
"POST /events HTTP/1.1" 422 Unprocessable Entity
ERROR 毒訊息，跳過：b'{"alert_id": "AGT_Room_301_Bed_...", ...}'
```

這正是 `ai/modules/chair_slip.py:40-49` 註解裡記載、stage2 已修過的**同一種破口**
（「早期版本曾在此直接 producer.send() 一份自訂 payload...會被後端 422 退件」）。
`chair_slip.py` 的修法是範本：**模組只偵測、回傳訊號，外發統一交回 `inference_test.py`
主迴圈的 `route_by_confidence()` 組 9 欄 payload**。

**同一段程式碼裡另外兩個模組，程式碼型態跟 micro_motion 一模一樣（自己組 payload 直送
`processed-reports`），推測有相同問題，但這次測試沒有實際觸發到它們，未經實測確認**：

| 模組 | 位置 | 送去哪 |
|---|---|---|
| `ai/modules/wandering.py`（模組 E，遊走） | `:36-48` | 直送 `processed-reports`，推測同款破口 |
| `ai/modules/bed_exit.py`（模組 A，離床） | `:40-52` | 直送 `processed-reports`，推測同款破口 |

`ai/modules/sanity_check.py`（模組 G，巡檢）送的是 `nursing-home-alerts`
（`:36-49`），會先經過 VLM 二審那層重新組包，**影響可能不同，也未經實測，一併列入待查**。

**這次沒有修**：跟片段存檔／S3 上傳兩件事無關，範圍不小（四個模組要逐一檢查與修正），
且需要跑得夠長的影片才能實測驗證每一個，留給接手者評估優先序後另案處理。

---

## 4.【待辦，尚未開始】agent P2：後端記錄 AI 判斷 + 前端顯示建議

**2026-07-27 確認**：stage5 只做了 agent 的 shadow 驗證（P0/P1/P4，`AGENT_SHADOW=1`），
P2（把 agent 的判斷接進後端資料庫、前端顯示出來）**完全沒有動過**——`backend/core/models.py`
的 `DetectEvent` 沒有任何 `ai_*` 欄位，前端也沒有任何 AI 建議相關元件。

**shadow 已經真的跑過、判斷品質可用**（`ai/agent_shadow.jsonl` 為證，非空談）：

```json
{"ai_verdict": "false_alarm", "ai_confidence": 0.8,
 "ai_reasoning": "根據影像，現場沒有任何人存在，因此可以確定並非真實的跌倒事件。"}
```

VLM 正確看出畫面沒人、agent 正確判定誤報並給出清楚理由——底層邏輯是可信的，值得接下去做。

**範圍（已拍板：只做 P2 的「A 層」，不做 cutover）**：
- **不**停掉現行 `uncertainty_router.py`／`vlm_worker.py`，agent **維持 shadow**，現行資料流不動。
- 只做「後端記錄 + 前端顯示」，讓 AI 的判斷變成人工複判時的**參考資訊**，不接手決策權。

**要做什麼（對照 `agent/docs/02-wbs.md` 的 P2 任務拆解，但拿掉 2.4/2.5 shadow 比對與 cutover）**：

| 任務 | 內容 | 對照 |
|---|---|---|
| 後端欄位 | `DetectEvent` 加 `ai_verdict`（`true_alarm｜false_alarm｜null`）／`ai_confidence`（float）／`ai_reasoning`（text），**皆 optional、向下相容**；`EventCreateRequest` 同步加；補 DB 遷移 | 欄位名稱與型別對齊 `agent/schemas.py:116-118`，agent 端已經是這個格式，不必再轉換 |
| 後端護欄 | **不得有任何自動關閉事件的程式路徑**——`false_alarm` 只存建議、`verdict` 留 NULL，關閉事件仍要人工按 | agent docs 的「不可退讓原則」第 2 條 |
| 前端顯示 | 事件卡／詳情顯示「AI 建議」徽章 + `ai_reasoning`；`ai_verdict=false_alarm` 時附「確認誤報」一鍵鈕，走既有 `PATCH /events/{id}/verdict`；無 AI 建議的舊事件（`ai_verdict=null`）顯示維持原樣 | — |
| 測試 | 三種路徑都要測：`true_alarm`／`false_alarm`／`null`（agent 判不出來）；舊格式訊息（無三欄）要照常建檔，既有 pytest 不可退 | — |

**驗證方式**：先把 `ai/agent_shadow.jsonl` 已經產出的判斷手動塞一筆進資料庫確認欄位/顯示正確，
不一定要等 agent 即時串接；真正要串接 agent 產出寫進 DB（而非只寫 log）是另一個小任務，
可以跟這個一起做，也可以先用假資料驗證前後端再補上。

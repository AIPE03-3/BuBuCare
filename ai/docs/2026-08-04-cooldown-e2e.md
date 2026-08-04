# 跌倒事件冷卻計時器：端到端實測

**日期**：2026-08-04ㅤ**分支**：`feat/verify-fall-cooldown`（從 `main` @ `b7843af` 開）
**機器**：5060 Ti（WSL2），Triton `action_transformer` v2 / `rt_detr` v2 / `yolo_pose` v1
**結論**：**三項驗收全過，程式沒有需要修的地方**
**2026-08-04 補測**：多路相機的冷卻互不干擾也已驗過（第六節 Run D／Run E），
原本列在「還沒驗到的」清單裡的那一項已移除。

---

## 〇、先更正一件事：這不是「從沒驗過」

本輪的任務描述說 commit `84c9920` 自己寫了「端到端驗收另外做」。
**實際查過 git 之後：那句話不存在。**

```
$ git log --all --format="%H %s" --grep="端到端驗收"
（無輸出）
```

`84c9920` 的 commit 訊息裡本來就有一段「實測」，而且已經涵蓋驗收①②：

> 實測（RTX 5060 Ti，Triton 三顆 READY）
> - 退路路徑 test7.mp4 單支：4 筆事件 + 每筆各一支 10 秒片段（改動前是 1 筆 1 支）。
> - 有追蹤器 test6.mp4：改動前後同為 2 筆、track id 相同（6、9），行為未變。
> - Kafka 兩個 topic 欄位如常，後端 POST /events 全 201、零 422。

所以本輪**不是補一個從沒做過的驗證**。真正新增的價值有三塊：

| | 為什麼還是值得跑 |
|---|---|
| **③「冷卻期間不會週期性洗版」** | `84c9920` 的實測**沒有涵蓋這項**。它是這個設計最容易被寫錯的地方（純看時間就會洗版），而且要專門造一支「人持續躺著」的素材才驗得到 |
| **跑在現在的整條鏈上** | `84c9920` 驗的時候線上還是 AcT **v1** 而且二審是 `vlm_worker`。現在是 AcT **v2** + `agent/` 二審，觸發時機與後段服務都換過了 |
| **驗到 DB 那一層** | 原本只驗到「後端 201」。這次是查 `GET /events`、下載 presigned URL 的片段、比對 md5 |

---

## 一、這個機制實際上是怎麼運作的

**冷卻只套在「ByteTrack 起不來」那條退路上**
（[`ai/inference_test.py:1121`](../inference_test.py#L1121) 的 `if person_tracker is None`）。
有追蹤器時走的是 per-track 閂鎖（`st["fired"]` + 站起來 `_FALL_RECOVERY_FRAMES` 幀解鎖），
本來就能重複發報。相機級冷卻若套上去會擋掉冷卻期間**別人**的跌倒。

重新武裝的規則在 [`_fallback_rearm()`](../inference_test.py#L224)：

```
冷卻到期  AND  畫面連續 _FALL_RECOVERY_FRAMES 個處理幀判非跌倒
```

**是 AND，不是 OR，也不是純看時間。** 這就是驗收③要打的點。

| 環境變數 | 預設 | 這次實測用的值 |
|---|---|---|
| `FALL_COOLDOWN_SEC` | 180 | 5（縮短以在單支影片內走完冷卻窗）|
| `FALL_RECOVERY_FRAMES` | 90 | Run A 用 10、Run B 用預設 90 |
| `MULTI_PERSON_TRACK` | 1 | Run A/B 用 `0`（強制走退路路徑）|

三個都走 `ai/backend_devices.py` 的 `cfg()`，**真實環境變數優先於 `.env`**，
所以是在指令前面帶，不改任何一行程式。

---

## 二、Run A —— ①能發第二筆 ②第二支片段也真的錄到

```bash
MULTI_PERSON_TRACK=0 FALL_COOLDOWN_SEC=5 FALL_RECOVERY_FRAMES=10 \
SINGLE_SOURCE=ai/test_demo/test7.mp4 HEADLESS=1 \
ai/.venv/bin/python -u ai/inference_test.py
```

log 原文（已濾掉 `h264_v4l2m2m` 硬體編碼器找不到的雜訊，那是既有的無害警告）：

```
🎯 [單源量測] SINGLE_SOURCE → 只掛一路：Room_301_Bed = /home/rapubuntu/aipe03-3/ai/test_demo/test7.mp4
👥 [Room_301_Bed] 逐人幾何判定：3 人通過門檻，best_idx=0（餵 AcT）｜判定倒地 (idx, 防線A, 防線B)=[(2, 1, 0)]
🚨 [Room_301_Bed] 跌倒事件已外發（topic=nursing-home-alerts，無追蹤器模式），接下來 5 秒進入冷卻
🖼️ [Room_301_Bed] 快照已上傳：s3://aipe03-3/snapshots/snapshot_Room_301_Bed_20260804_162845.jpg
🎬 [Room_301_Bed] 事件片段已寫入（76 幀 @ 15.0fps，libx264 (PyAV)）：/home/rapubuntu/aipe03-3/ai/clips/clip_Room_301_Bed_20260804_162845.mp4
📦 [Room_301_Bed] 片段已上傳：s3://aipe03-3/videos/clip_Room_301_Bed_20260804_162845.mp4
 [FPS/穩態(含節流)] [Room_301_Bed] 區間   7.3 fps｜累計均   7.3 fps（已處理 60 幀）
                            …（中間 180 幀，畫面在跌倒與正常之間來回）…
ℹ️ [Room_301_Bed] 冷卻已過且畫面回到正常 10 個處理幀，解除本路相機的 fall 事件閂鎖
🚨 [Room_301_Bed] 跌倒事件已外發（topic=nursing-home-alerts，無追蹤器模式），接下來 5 秒進入冷卻
🖼️ [Room_301_Bed] 快照已上傳：s3://aipe03-3/snapshots/snapshot_Room_301_Bed_20260804_162912.jpg
🎞️ [Room_301_Bed] 影像流結束，後段未錄滿 → 補寫已收到的片段
🎬 [Room_301_Bed] 事件片段已寫入（98 幀 @ 15.0fps，libx264 (PyAV)）：/home/rapubuntu/aipe03-3/ai/clips/clip_Room_301_Bed_20260804_162912.mp4
📦 [Room_301_Bed] 片段已上傳：s3://aipe03-3/videos/clip_Room_301_Bed_20260804_162912.mp4
```

**① 第二筆事件發出來了**，而且中間那行 `ℹ️ …解除本路相機的 fall 事件閂鎖`
證明它是**走冷卻解鎖出來的**，不是繞過閂鎖。

**② 兩支片段是不同的檔**，不是同一支被讀兩次：

```
$ ls -la ai/clips/clip_Room_301_Bed_20260804_1628*.mp4 ai/clips/clip_Room_301_Bed_20260804_1629*.mp4
-rw-r--r-- 1 rapubuntu rapubuntu 348889 Aug  4 16:28 ai/clips/clip_Room_301_Bed_20260804_162845.mp4
-rw-r--r-- 1 rapubuntu rapubuntu 402291 Aug  4 16:29 ai/clips/clip_Room_301_Bed_20260804_162912.mp4

clip_Room_301_Bed_20260804_162845.mp4 幀數=76 長度=5.1s 640x360
clip_Room_301_Bed_20260804_162912.mp4 幀數=98 長度=6.5s 640x360

$ md5sum …
a32c1be499e157b328dd007bc1afcb49  clip_Room_301_Bed_20260804_162845.mp4
7a9c277cea76cf54045411da2041adb0  clip_Room_301_Bed_20260804_162912.mp4
```

第二支 98 幀是因為影片播完了、後段沒錄滿就補寫（log 那行 `後段未錄滿 → 補寫` 說明了原因），
不是錄壞。

---

## 三、Run B —— ③冷卻期間不會週期性洗版（本輪真正新增的驗證）

### 為什麼要另外造素材

`ai/test_demo/` 裡沒有一支是「人倒下之後就一直躺著沒人處理」——那正是這個機制最該擋、
也最容易寫錯的情境（純看時間的實作會每 `FALL_COOLDOWN_SEC` 補一筆）。

所以自己造了一支：取 `ai/test_demo/test8.mp4` 的 **9.0~12.5s**，重複 18 次接成 **62.3 秒**。

這個時間區間是**逐幀看畫面挑出來的**：10.0s 那格是「該人整個趴在地上」、13.0s 那格已經站起來，
所以 9.0~12.5s 這段從頭到尾都是倒地狀態，接起來才不會混進「已經站起來」的幀
（混到的話畫面會回到正常，反而把閂鎖解開，這支素材就白造了）。

> 這組時間點原本是在部署 AcT v2 時逐幀確認的，紀錄在 `feat/act-v2-deploy` 分支的
> `ai/docs/2026-08-04-act-v2-deploy.md` 第三節。**那份文件不在本分支上**，所以這裡不放連結，
> 直接把結論寫明。等該分支併進 `main` 之後才查得到原始逐幀紀錄。

產生腳本與素材都是暫存的，不進版控；作法完整記在本節，可重現：

```python
# 抽 test8.mp4 的 9.0~12.5s（52 幀）→ 重複 18 次 → 936 幀 ≈ 62.3s，libx264/yuv420p
```

### 跑法與結果

```bash
MULTI_PERSON_TRACK=0 FALL_COOLDOWN_SEC=5 FALL_RECOVERY_FRAMES=90 \
SINGLE_SOURCE=<lying_loop.mp4> HEADLESS=1 \
ai/.venv/bin/python -u ai/inference_test.py
```

冷卻只有 5 秒、影片 62 秒 → **中間有大約 12 個冷卻窗到期**。

```
外發次數: 1
解除閂鎖次數: 0
```

log 原文（全長只有 42 行，這裡是關鍵部分）：

```
🎯 [單源量測] SINGLE_SOURCE → 只掛一路：Room_301_Bed = …/lying_loop.mp4
👥 [Room_301_Bed] 逐人幾何判定：3 人通過門檻，best_idx=1（餵 AcT）｜判定倒地 (idx, 防線A, 防線B)=[(1, 1, 1)]
🚨 [Room_301_Bed] 跌倒事件已外發（topic=nursing-home-alerts，無追蹤器模式），接下來 5 秒進入冷卻
🖼️ [Room_301_Bed] 快照已上傳：s3://aipe03-3/snapshots/snapshot_Room_301_Bed_20260804_163103.jpg
🎬 [Room_301_Bed] 事件片段已寫入（105 幀 @ 15.0fps，libx264 (PyAV)）：…/clip_Room_301_Bed_20260804_163103.mp4
📦 [Room_301_Bed] 片段已上傳：s3://aipe03-3/videos/clip_Room_301_Bed_20260804_163103.mp4
 [FPS/穩態(含節流)] [Room_301_Bed] 區間   6.6 fps｜累計均   6.6 fps（已處理 60 幀）
👥 [Room_301_Bed] 逐人幾何判定：3 人通過門檻，best_idx=1（餵 AcT）｜判定倒地 (idx, 防線A, 防線B)=[(1, 1, 1)]
                            …（同樣的判定倒地行連續出現 18 次）…
 [FPS/穩態(含節流)] [Room_301_Bed] 區間   7.5 fps｜累計均   6.7 fps（已處理 420 幀）
👥 [Room_301_Bed] 逐人幾何判定：3 人通過門檻，best_idx=1（餵 AcT）｜判定倒地 (idx, 防線A, 防線B)=[(1, 1, 1)]
👥 [Room_301_Bed] 逐人幾何判定：3 人通過門檻，best_idx=1（餵 AcT）｜判定倒地 (idx, 防線A, 防線B)=[(1, 1, 1)]
⏳ [Room_301_Bed] 影像流讀取結束，強行等待後端 MLOps 管線與 VLM 二審完成...
```

**判斷依據**：整支片子共 420+ 個處理幀，`判定倒地 (idx, 防線A, 防線B)=[(1, 1, 1)]` 這行
出現 18 次（兩道防線一路都成立，人從頭到尾在地上），冷卻窗到期了大約 12 次，
但 `🚨 …已外發` **只有一次**、`ℹ️ …解除本路相機的 fall 事件閂鎖` **一次都沒有**。

這就是 `_fallback_rearm()` 那個 `and` 在起作用：時間條件早就滿足了，
但「畫面連續 90 個處理幀判非跌倒」永遠不成立，所以閂鎖不解。
**如果當初寫成純看時間，這裡會出現 12 筆事件、12 支片段。**

---

## 四、Run C —— 對照組：有追蹤器時冷卻不該擋別人

```bash
FALL_COOLDOWN_SEC=180 SINGLE_SOURCE=ai/test_demo/test7.mp4 HEADLESS=1 \
ai/.venv/bin/python -u ai/inference_test.py
```

（`MULTI_PERSON_TRACK` 不設 = 預設 1，ByteTrack 正常運作）

```
外發次數: 4
🚨 [Room_301_Bed] 第 1 位（track 4）跌倒事件已外發（topic=nursing-home-alerts，連續 4 幀判定成立）
🚨 [Room_301_Bed] 第 2 位（track 3）跌倒事件已外發（topic=nursing-home-alerts，連續 4 幀判定成立）
🎬 [Room_301_Bed] 事件片段已寫入（132 幀 @ 15.0fps，libx264 (PyAV)）：…/clip_Room_301_Bed_20260804_163337.mp4
🚨 [Room_301_Bed] 第 3 位（track 10）跌倒事件已外發（topic=nursing-home-alerts，連續 4 幀判定成立）
🚨 [Room_301_Bed] 第 4 位（track 1）跌倒事件已外發（topic=nursing-home-alerts，連續 4 幀判定成立）
🔁 [Room_301_Bed] track 13 與 30 秒內已發報的人位置幾乎重合（中心距離 0.30 個身位），判定為同一人換號，不重複發事件
🔁 [Room_301_Bed] track 15 與 30 秒內已發報的人位置幾乎重合（中心距離 0.16 個身位），判定為同一人換號，不重複發事件
🎬 [Room_301_Bed] 事件片段已寫入（148 幀 @ 15.0fps，libx264 (PyAV)）：…/clip_Room_301_Bed_20260804_163352.mp4
```

**冷卻設 180 秒，但整支 27 秒的片子照樣發了 4 筆** —— 證實冷卻確實只套退路路徑，
沒有誤傷 per-track。同位置去重也有在動（track 13/15 被判成換號的同一人，沒重複發）。

**4 筆事件只有 2 支片段是設計如此**，不是漏錄：多人同時跌倒共用同一支片段
（[`ai/inference_test.py:1275-1281`](../inference_test.py#L1275-L1281) 的註解說明了為什麼——
錄影是單一插槽，第二個人重啟錄影會把第一個人的後段截斷）。

---

## 五、端到端：Kafka → agent 二審 → 後端 DB

三輪合計發出 **7 筆**慢速道事件（Run A 2 + Run B 1 + Run C 4）。

| | 三輪之前 | 三輪之後 | 差 |
|---|---|---|---|
| `nursing-home-alerts` offset | 197 | 204 | **+7** |
| `processed-reports` offset | 262 | 269 | **+7** |
| 後端 `GET /events` 筆數 | 32 | 39 | **+7** |

**1:1，沒有任何一筆重複或掉件。** agent consumer group 的 lag 是 0：

```
GROUP           TOPIC               PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG
agent-reviewer  nursing-home-alerts 0          204             204             0
```

後端 DB 裡的七筆（`GET /events`）：

```
2026-08-04T16:28:45  51327b3c  clip=clip_Room_301_Bed_20260804_162845.mp4  ai=true_alarm   ← Run A 第 1 筆
2026-08-04T16:29:12  b3a2d27a  clip=clip_Room_301_Bed_20260804_162912.mp4  ai=true_alarm   ← Run A 第 2 筆（冷卻放行）
2026-08-04T16:31:03  dcf9029a  clip=clip_Room_301_Bed_20260804_163103.mp4  ai=true_alarm   ← Run B 唯一一筆
2026-08-04T16:33:37  91e0b744  clip=clip_Room_301_Bed_20260804_163337.mp4  ai=true_alarm   ← Run C
2026-08-04T16:33:40  b5a59d9b  clip=clip_Room_301_Bed_20260804_163337.mp4  ai=true_alarm   ← Run C（共用片段）
2026-08-04T16:33:52  573e10ed  clip=clip_Room_301_Bed_20260804_163352.mp4  ai=true_alarm   ← Run C
2026-08-04T16:33:52  a2f405a0  clip=clip_Room_301_Bed_20260804_163352.mp4  ai=true_alarm   ← Run C（共用片段）
```

**Run A 那兩筆在 DB 裡帶的是不同的 `clip_path`** —— 這是驗收②在 DB 層的證據。
再往下走一層，兩支片段從 S3 presigned URL 都真的下載得到，而且大小與本機檔**完全一致**：

```
51327b3c clip 下載 -> HTTP 200  size=348889 bytes   （本機 348889）
b3a2d27a clip 下載 -> HTTP 200  size=402291 bytes   （本機 402291）
```

> 註：這三輪跑的時候二審已經是 `agent/`（第 5 批剛 cutover），所以七筆的
> `ai_verdict` 都有值。`vlm_worker` 沒有在跑，不存在雙寫。

---

## 六、Run D / Run E —— 多路相機的冷卻互不干擾（2026-08-04 補測）

前一版這份文件的第八節把「多台相機各自的冷卻互不干擾」列為**未驗**，理由是三輪都只掛一路
（`SINGLE_SOURCE`），沒實際跑多路確認 dict 的 key 不會互相蓋掉。本節補上。

### 先看程式：隔離是靠什麼成立的

冷卻狀態宣告在 [`ai/inference_test.py:618`](../inference_test.py#L618)：

```python
    fall_cooldown_until = {}   # event_type -> 冷卻到期的 epoch 秒
    # 下面兩個只有「沒有追蹤器」那條退路在用（有追蹤器走 per-track 閂鎖，見 person_states）。
    cam_armed = True           # 現在允不允許發報
    cam_recovery_frames = 0    # 連續幾個處理幀判定非跌倒（與 st["recovery"] 同語意）
```

這三個都是 [`camera_worker()`](../inference_test.py#L548)（第 548 行）的**函式區域變數**
（縮排 4 格＝函式本體，不是巢狀的 `_reconnect()` 裡面），而
[第 1456-1458 行](../inference_test.py#L1456-L1458)是**一路相機開一條執行緒**：

```python
    for cam_id, stream_src in camera_channels.items():
        t = threading.Thread(target=camera_worker, args=(cam_id, stream_src))
        t.daemon = True; threads.append(t); t.start()
```

所以每路相機各自有一份獨立的堆疊框，`fall_cooldown_until` 根本不是共用的 dict——
**隔離來自變數作用域，不是來自 key 的設計**。dict 的 key 只有 `event_type` 而沒有相機名，
正是因為「worker 本來就一路相機一個」（第 616-617 行的註解就是這樣寫的）。
`camera_worker` 唯一的 `global` 宣告在[第 549 行](../inference_test.py#L549)，
裡面是 producer／模型／顯示用的 `output_frames`，**不含任何冷卻狀態**。

下面兩輪是把這個結論實際跑出來。兩輪都 `MULTI_PERSON_TRACK=0`（強制走吃冷卻的退路路徑），
用 `STRESS_CAM_COUNT=3` 掛三路（`Room_301/302/303` → `test1/2/3.mp4`）。

### Run D：冷卻 180 秒，三路照樣各發各的

```bash
MULTI_PERSON_TRACK=0 FALL_COOLDOWN_SEC=180 FALL_RECOVERY_FRAMES=90 \
STRESS_CAM_COUNT=3 HEADLESS=1 \
ai/.venv/bin/python -u ai/inference_test.py
```

log 原文：

```
🔥 [壓測] STRESS_CAM_COUNT=3 → 掛 3 路併發頻道：['Room_301_Bed', 'Room_302_Bed', 'Room_303_Bed']
🚨 [Room_301_Bed] 跌倒事件已外發（topic=processed-reports，無追蹤器模式），接下來 180 秒進入冷卻
🖼️ [Room_301_Bed] 快照已上傳：s3://aipe03-3/snapshots/snapshot_Room_301_Bed_20260804_172255.jpg
🚨 [Room_303_Bed] 跌倒事件已外發（topic=processed-reports，無追蹤器模式），接下來 180 秒進入冷卻
🖼️ [Room_303_Bed] 快照已上傳：s3://aipe03-3/snapshots/snapshot_Room_303_Bed_20260804_172258.jpg
🚨 [Room_302_Bed] 跌倒事件已外發（topic=nursing-home-alerts，無追蹤器模式），接下來 180 秒進入冷卻
🖼️ [Room_302_Bed] 快照已上傳：s3://aipe03-3/snapshots/snapshot_Room_302_Bed_20260804_172301.jpg
```

**三路的發報時刻是 17:22:55 / 17:22:58 / 17:23:01，前後只差 6 秒，而冷卻設的是 180 秒。**
如果冷卻狀態是跨相機共用的，第一路在 17:22:55 進入冷卻之後，另外兩路會被壓到 17:25:55，
整支跑不到 30 秒的測試裡就**只會有 1 筆**。實際是 3 筆，一路一筆。

三支片段也是各自獨立的檔（幀數對得上各自的來源影片 187/284/268）：

```
-rw-r--r-- 1 rapubuntu rapubuntu 229427 17:23:02 ai/clips/clip_Room_301_Bed_20260804_172255.mp4
-rw-r--r-- 1 rapubuntu rapubuntu 255181 17:23:06 ai/clips/clip_Room_303_Bed_20260804_172258.mp4
-rw-r--r-- 1 rapubuntu rapubuntu 212245 17:23:06 ai/clips/clip_Room_302_Bed_20260804_172301.mp4
```

順帶看到信心分流也在動：301／303 直接進 `processed-reports`（快速道），
302 走 `nursing-home-alerts`（慢速道二審）。

### Run E：冷卻 5 秒，三路的解鎖時機各走各的

Run D 證明了「不會互相擋」，但沒證明「解鎖也是各算各的」（180 秒內沒有任何一路解鎖過）。
Run E 把冷卻縮到 5 秒、恢復幀數縮到 10，讓解鎖在影片長度內來得及發生：

```bash
MULTI_PERSON_TRACK=0 FALL_COOLDOWN_SEC=5 FALL_RECOVERY_FRAMES=10 \
STRESS_CAM_COUNT=3 HEADLESS=1 \
ai/.venv/bin/python -u ai/inference_test.py
```

log 原文（依出現順序，含行號）：

```
11:🚨 [Room_301_Bed] 跌倒事件已外發（topic=processed-reports，無追蹤器模式），接下來 5 秒進入冷卻
17:🚨 [Room_303_Bed] 跌倒事件已外發（topic=processed-reports，無追蹤器模式），接下來 5 秒進入冷卻
19:🚨 [Room_302_Bed] 跌倒事件已外發（topic=nursing-home-alerts，無追蹤器模式），接下來 5 秒進入冷卻
30:ℹ️ [Room_303_Bed] 冷卻已過且畫面回到正常 10 個處理幀，解除本路相機的 fall 事件閂鎖
32:ℹ️ [Room_302_Bed] 冷卻已過且畫面回到正常 10 個處理幀，解除本路相機的 fall 事件閂鎖
```

| 相機 | 發報 | 解鎖 |
|---|---|---|
| `Room_301_Bed` | 1 次 | **0 次** |
| `Room_302_Bed` | 1 次 | 1 次 |
| `Room_303_Bed` | 1 次 | 1 次 |

**這裡的關鍵是 301 和另外兩路不一樣**：302／303 解了鎖，301 從頭到尾沒解過。
三路的冷卻到期時間幾乎一樣（發報只差 6 秒），所以差別不在時間那半邊，
而在 `_fallback_rearm()` 的另一半——「畫面連續 10 個處理幀判非跌倒」。
301 跑的 `test1.mp4` 只有 187 幀，跑完之前沒有湊滿 10 個非跌倒幀。

也就是說 `cam_armed` / `cam_recovery_frames` 這兩個狀態在三路之間**走出了不同的值**。
共用一份的話不可能出現這種分歧。

> 三路解鎖後都沒有再發第二筆，是因為影片在解鎖後就播完了（test1/2/3 只有 8~9 秒），
> 不是被擋住。「解鎖後發得出第二筆」那項是 Run A 驗的，不重複。

### 端到端

| | Run D 前 | Run E 後 | 差 |
|---|---|---|---|
| `nursing-home-alerts` offset | 204 | 206 | +2 |
| `processed-reports` offset | 269 | 275 | +6 |
| 後端 `GET /events` 筆數 | 39 | 45 | **+6** |

兩輪各 3 筆共 6 筆，後端剛好 +6，**沒有重複也沒有掉件**。
`processed-reports` +6 = 快速道 4 筆直入 + 慢速道 2 筆經 agent 二審後轉入；
`nursing-home-alerts` +2 就是那 2 筆慢速道。agent lag 0：

```
GROUP           TOPIC               PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG
agent-reviewer  nursing-home-alerts 0          206             206             0
```

後端 DB 裡六筆的 `camera_id` 與 `clip_path` 都是分開的（`GET /events`，節錄）：

```
2026-08-04T17:25:57  2b4fb4a9  302  clip=clip_Room_302_Bed_20260804_172557.mp4  ai=true_alarm
2026-08-04T17:25:55  4d987092  303  clip=clip_Room_303_Bed_20260804_172555.mp4  ai=None
2026-08-04T17:25:52  4b7a4c01  301  clip=clip_Room_301_Bed_20260804_172552.mp4  ai=None
2026-08-04T17:23:01  79427890  302  clip=clip_Room_302_Bed_20260804_172301.mp4  ai=true_alarm
2026-08-04T17:22:58  b3fbddf1  303  clip=clip_Room_303_Bed_20260804_172258.mp4  ai=None
2026-08-04T17:22:55  cf5f24b4  301  clip=clip_Room_301_Bed_20260804_172255.mp4  ai=None
```

走快速道的四筆 `ai_verdict` 是 `None`（沒經過二審，本來就不會有值），
走慢速道的兩筆是 `true_alarm`。這與信心分流的設計一致，不是漏寫。

**結論：多路相機的冷卻互不干擾，這項從「未驗」改為「已驗」。**

---

## 七、沒有發現需要修的東西

三項驗收全過，程式行為與 `_fallback_rearm()` 的設計意圖一致，**這次沒有改任何一行
`ai/inference_test.py`**。

單元測試也已經覆蓋這條規則，不需要補：

```
$ python -m pytest ai/tests/test_fall_gates.py -q
10 passed in 3.44s
```

其中 `test_冷卻到期但畫面仍判跌倒時不重新武裝且恢復計數歸零`
（[`ai/tests/test_fall_gates.py:28`](../tests/test_fall_gates.py#L28)）就是 Run B 的單元版。
Run B 的價值在於**證明那條單元測試描述的行為在真實影像上也成立**——
單元測試餵的是布林值，實跑餵的是畫面。

---

## 八、驗證指令與結果

```
python scripts/check_guardrails.py       → ✅ 護欄檢查通過（掃了 438 個檔案）
python -m pytest agent ai scripts -q     → 191 passed in 4.03s
python -m pytest ai/tests/test_fall_gates.py -q → 10 passed
```

> 檔案數從 437 變 438 不是多冒出檔案：護欄掃的是 `git ls-files`
> （[`scripts/check_guardrails.py:124`](../../scripts/check_guardrails.py#L124)），
> 第一版是在 commit 前跑的，當時本文件還沒被追蹤。

> 本分支從 `main` 開，所以是 191 passed。第 5 批（`feat/agent-cutover`，PR #36）
> 新增的 11 支不在這條分支上。

服務狀態：backend `/health` 200、Triton `action_transformer` **v2** /
`rt_detr` v2 / `yolo_pose` v1 全 READY、`agent/` 正在跑（第 5 批 cutover 後的正式二審）。

---

## 九、還沒驗到的

**以下三項是刻意不驗的**——使用者已明確指示「都以拍好的跌倒影片去跑系統測試」，
真設備與現場資料本輪不取得。留在這裡是為了不造成「已經全驗過」的假象。

- **真攝影機**：五輪全部是 mp4。冷卻這個機制當初就是為了「worker 一跑好幾天」的
  真攝影機情境而做的，但 RTSP 長時間運行仍然沒有實測過。
- **`FALL_COOLDOWN_SEC` 的預設值 180 秒合不合用**：本輪為了在影片長度內走完冷卻窗
  多半縮短成 5 秒（Run D 有用滿 180 秒，但那是拿來證明隔離，不是驗這個值合不合適）。
  180 仍然只是「改動前等於無限長，保守往長抓」的推測值，沒有現場資料支持。
- **`event_type` 值域只有 `"fall"`**，所以「每種事件類型各一份冷卻」這半邊等於沒被驗到。
  要驗得等真的有第二種事件類型（離床／座椅滑落）接進 `route_by_confidence()`。

**已於 2026-08-04 補驗、從本清單移除**：多台相機各自的冷卻互不干擾 → 見第六節 Run D／Run E。

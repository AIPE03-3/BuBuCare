# 已完成階段的紀錄

這份是**歷史檔案**：`NEXT_STAGE.md` 裡標【已完成】的項目搬到這裡，讓那份回歸「待辦」的本義。

**項目編號刻意沿用原本的**（第 1、2、3、6、7、8、9、10 項）—— 程式碼註解與其他文件
有 6 處引用「第 N 項」「缺陷三」，改號會把它們全部打斷。

> **讀這份的心法**：這裡記的是「當時做了什麼、為什麼那樣做、踩過哪些坑」。
> 有價值的多半不是結論本身，而是**「為什麼用當時的測法測不出來」**那幾段。
> 想知道系統現在長什麼樣、哪裡還是壞的，看 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

**第 9 項有兩個缺陷至今未修**（缺陷三 `normal_h_reference`、缺陷四 體角與俯視佈署不符），
雖然整項標【已完成】。未修的部分在 [`../NEXT_STAGE.md`](../NEXT_STAGE.md) 有指標。

---

## 10.【已完成】MLOps 進版控 —— 換一台機器整條不再消失

分支 `feat/mlops-into-vcs`。完整 runbook 見 **[`ai/MLOPS.md`](../ai/MLOPS.md)**。

### 原本壞在哪

MLOps 是本專案主打的一環，但版控裡幾乎不存在，**換一台機器整條就沒了**。
實際查下去比預期的還糟，四條路徑同時是斷的：

1. **`ai/export_models.py` 不存在**，但 `CONTRIBUTING.md:24`、`ai/run_triton.sh:82`、
   `scripts/check_guardrails.py:131` **三個地方都叫人跑它**重建模型。
2. **`ai/data.yaml` 不存在**，訓練腳本指向它，所以在這台從來沒跑起來過。
3. **`ai/webhook_receiver.py` 已進版控，但第 13 行 import 的 `submit_task` 從來不存在**
   —— 自動點火那條 import 就掛。這條原本沒被列進來，是查的時候才發現的。
4. 訓練腳本沒進版控，而且寫死 `/home/rapubuntu/...`，直接 commit 會被護欄擋。

### 做了什麼

八支腳本移植進 `ai/`（來源是 `origin/albert_chiang:Fall/tools/`），路徑全走 `cfg()`
或 `__file__` 基準，護欄全綠。ClearML / Label Studio 的 compose 也進版控，
volume 名沿用既有的，接得上這台先前的實驗與標註資料。

### 上游那份**照抄就會出事**的地方（這是這輪最有價值的部分）

每一個都是「跑得動、不報錯、結果是錯的」那種，靠 code review 抓不到：

| # | 照抄會怎樣 |
|---|---|
| 1 | **`data.yaml` 的類別名整組錯**。上游是 wheelchair/slipper/wire/obstacle/walker，這台的資料其實是 person/chair/sofa/bed/tv。訓練照樣成功，只是每個類別的語意都不對 |
| 2 | **假標註被截成合理的框**。上游的清洗是「每行留前 5 欄」，那 21 個寫死的假 pose 標註截完會變成看起來很正常、實際憑空捏造的框混進訓練集 |
| 3 | **mAP 是拿訓練集量的**。上游 `data.yaml` 的 `train` 與 `val` 指同一個目錄 |
| 4 | **滾動式重訓從來沒滾動過**。上游用 `Model.created` 排序找上一輪最強模型，那個欄位在 clearml 2.1.10 不存在，AttributeError 被 except 吞掉、每輪冷啟動 |
| 5 | **一輪爛訓練會毒害後續所有輪**。上游每輪無條件標 `best`，下一輪去繼承它、部署端抓它上線 |
| 6 | **部署打到 backend**。上游 Triton 埠寫死 8000，那是這台 backend 的 uvicorn |
| 7 | **部署失敗會謊報成功**。上游有一段「連不上 Triton 就 return True」（他 Mac 沒 N 卡）|
| 8 | **只丟 ONNX 會讓整支 Triton 起不來**。這台 `rt_detr` 是 `tensorrt_plan`，要編 Blackwell 引擎 |

### 實測數字

| 項目 | 結果 |
|---|---|
| 模型重建 | 三顆全部從 `.pt`/`.pth` 重建，`rt_detr` 的 TensorRT 引擎 69.1MB（trtexec FP16，3m57s），Triton 三顆 READY |
| 資料清洗 | 標註行保留 362 / 丟棄 41；圖片 111 → 可用 90、隔離 21；train 72 / val 18 |
| 重訓 | 100 epochs / batch 8 / 0.155 小時，**mAP50=0.9912、mAP50-95=0.9851** |
| 熱部署 | `rt_detr` v1 → v2，v2 READY 200 / v1 400；同張圖推論輸出確實改變（7 框 COCO → 5 框新類別）|
| 推論與 fps | `test6.mp4` 部署前 8.3 fps → 部署後 **8.4 fps**（+1.2%），兩次都抓到同樣兩位跌倒者、片段幀數一致 |
| 回滾 | `--rollback` 實測可用，v1 回到 READY |

### ⚠️ mAP 0.99 不要拿去當泛化能力的證據

111 張快照來自同幾個房間同幾支相機、內容高度重複（同一行標註出現在 22 個檔案裡），
80/20 隨機切分會把「同場景相鄰幾秒」的畫面分到 train 與 val 兩邊 —— 等於考已經念過的
內容。而且 `bed` 一個標註都沒有、`sofa` 只有 5 個框。

**這個數字證明的是「重訓管線是通的」，不是「模型在新病房也有 99%」。**
要回答後者得補資料、並改成**按場景/相機/日期分組切分**。這是下一步最該做的事，
不是再調參數。理由與細節見 [`ai/MLOPS.md`](../ai/MLOPS.md) 第三節。

### 順手修好的兩件事

- **ClearML 的 fileserver 與 webserver 壞了一週沒人發現**（`docker ps -a` 顯示
  Exited 7 天 / 3 天，只有 apiserver 活著）。原因是它們照上游 compose 的**服務名**
  互打（nginx 寫死 `upstream apiserver`、fileserver 連 `redis:6379`），而手動
  `docker run` 起的容器沒有那些名字。fileserver 是模型權重的落地點，它掛著等於
  重訓產物根本存不上去。compose 補 network aliases 就解了。
- `ai/triton_detr_client.py` 的 `NAMES` 仍是 COCO 80 類，與 v2 的 5 類對不上。
  現在**不會壞**（唯一下游 `inference_test.py:714-728` 算完沒有任何地方讀，
  原讀取者 `bed_exit`/`chair_slip` 已刪），但已在該檔寫明：要把那兩個值接回使用前，
  先對齊當下 serving 版本的類別表。

---

## 7.【已完成】接回 main 的 `stream_channel` 改名 —— 後端從全面 500 救回來

`devices` 的欄位改名（`stream_url` → `stream_channel`，`origin/main` `51871e5`，PR #15）
已經施作在**共用的正式 RDS** 上，但本測試分支的後端 model 還停在舊名字，導致
`GET /devices`、`GET /events`、`POST /events` **全部 500**——前端事件中心整頁空白，
AI 偵測到的跌倒卡在 Kafka 進不了資料庫（20 分鐘內重試失敗 68 次）。

**壞得很安靜**：四個容器全綠、AI 端 log 一路正常，只有翻後端日誌才看得到。

合併 `origin/main` 之後，還要補三個 **git 自動合併成功、但語意已壞**的地方——兩邊改的是
同一個檔的不同段落，diff 上看不出問題，一執行就 `TypeError: 'stream_url' is an invalid
keyword argument`：`devices/router.py` 的 `POST /devices`、`init_db.py` 的種子、
`test_devices_create.py`。種子同時改成種**頻道名**而非完整 `rtsp://` 網址（種完整網址
正是這次改名要根除的錯誤用法：那種位址只在填寫者自己的機器上有效）。

順手修掉的第二個 bug：`TRITON_*_URL` 是全檔唯一還用 `os.environ.get` 直接讀的設定，
繞過了 `cfg()`，所以寫進根目錄 `.env` **完全沒有效果**；加上預設值是被 backend 佔用的
8000，後果是每一幀都打到 FastAPI 拿 404 然後靜默降級——影片照跑、FPS 照印、零紅字，
**姿態偵測全程失效**。已改走 `cfg()`、預設 8010。

---

## 8.【已完成】偵測畫面推流：前端「偵測」看得到真的姿態框

kelly 已經做好前端「即時／偵測」切換鈕、後端 `stream_channel_detect`、MediaMTX 的
`cam_out` 頻道，但 `cam_out` 是 `source: publisher`（開著門等人推），**沒有任何程式在推**，
所以切到「偵測」永遠是空的。設定檔註解原本寫「正式來源是 albert 的推論程式，尚未實作」。

新增 [`ai/detect_publisher.py`](../ai/detect_publisher.py)，把 `inference_test.py` 早就畫好的
`annotated_frame` 多開一條出口推回 MediaMTX：開一支 **ffmpeg 子程序**，stdin 收 BGR 原始幀，
編成 H.264 推進去。與 kelly 的 `start-fake-detect.ps1` 走同一條路（ffmpeg → rtsp），
差別只在畫面來源從「ffmpeg 自己畫的固定紅框」換成「AI 真正畫的骨架與框」。

**需要機器上裝 ffmpeg**（`sudo apt install ffmpeg` / `winget install Gyan.FFmpeg`）。
裝在非標準位置時可用 `DETECT_STREAM_FFMPEG` 指定完整路徑。找不到就不推流並印訊息，
其餘功能完全不受影響（三種降級路徑都實測過）。

### ⚠️ 事件片段與快照「刻意」維持無框，不要修好它

**這是組長的決策，不是缺陷**：警示彈窗要人當下確認，畫面上有框會干擾判讀。要看框請走
即時串流的「偵測」那一半，UI 上已經分好了。

所以：**不要把 `annotated_frame` 接進 `write_event_clip()` 或快照存檔**。
兩條路實測確認是分開的——同一次跑，`cam_out` 讀回來有骨架與 `person 0.90` 的框，
事件片段同一時段的畫面乾淨無框。

### 實測踩到的坑：時間戳這組參數兩個都不能少

`-use_wallclock_as_timestamps 1` 與 `-fps_mode cfr` 要一起用：

- **少了 wallclock**：rawvideo 照 `-r` 推算時間，但推論的實際張數低於名目值且會變動，
  串流會變慢動作、延遲一路累積不會回頭。
- **少了 CFR 整流**：光靠真實時鐘，編碼器以 `-r` 的刻度記時間戳，推論速度一抖動、
  相鄰兩幀擠進同一格就 DTS 撞號，整條推流直接斷掉。

**這個坑值得記**：平順推流時完全正常（連推兩百多幀沒事），只有在速度抖動的那一瞬間
才炸。驗證時要刻意用「爆量＋停頓」的不規則節奏測，等速測試看不出來。
實測 200 幀不規則節奏：送出 187、丟 13、零中斷。

### 開關與已知限制

- `DETECT_STREAM=1` 才推，未設＝位元級原行為（已實測）。
- 需要 ffmpeg；沒裝、或 `DETECT_STREAM_FFMPEG` 指到不存在的路徑，都會印訊息後略過推流
  （兩種都實測過，不影響其他功能）。
- 與 `NO_RENDER=1` 互斥（那個開關跳過畫框，等於沒畫面可推），偵測到會明講並停用。
- 推流的 FPS 成本：10.1（未推流 10.5~12），約在雜訊範圍邊緣，可接受。
- 這台機器沒有 MediaMTX 也沒有 ffmpeg，驗證時是臨時抓 MediaMTX v1.19.3 與免安裝的
  靜態 ffmpeg 7.0.2 起在本機跑的。要在這台常態使用，得把兩者都裝好並設
  `MEDIAMTX_BASE_URL`（目前刻意留空＝灰色占位框）。

---

## 9.【已完成】接真攝影機（手機 + Tapo C210）實測 —— 抓出四個被 demo 影片掩蓋的問題

先用手機推流、再接 Tapo C210 IP 攝影機各跑一輪，**共暴露四個用 `fall-demo.mp4` 測一百次
都不會發現的問題**。前兩個已修，後兩個已診斷定位、依決議留待與模型調校一起處理。

這一節記下來是因為「為什麼影片測不出來」比修法本身更值得記 —— 四個的共同點都是
**影片來源固定不變**，而真攝影機會動、會換、會有不同的架設角度。

| # | 問題 | 狀態 |
|---|---|---|
| 1 | 跌倒紅框永久卡死 | ✅ 已修（`88c90c0`）|
| 2 | 體角只涵蓋一半躺向 | ✅ 已修（`249f132`）|
| 3 | `normal_h_reference` 換來源不重設 | 📋 已診斷，未修 |
| 4 | 體角前提與俯視佈署不符 | 📋 已診斷，未修（最需要正視）|

### 缺陷一：紅框永久卡死（已修）

畫面上的 `FALL DETECTED!` 紅框掛在 `ever_detected_fall` 這個只進不出的旗標上，
第一次觸發之後條件恆為真，**畫面永遠是紅的**，不管現場現在什麼狀況。

**影片測不出來的原因**：影片檔播完 worker 就結束，鎖不鎖沒差。真攝影機的 worker
一跑好幾天 —— 那台相機第一次觸發之後，值班人員再也無法從畫面判斷現在有沒有事，
這個指示燈等於失效。

修法：把「顯示」與「歷史記錄」拆開。`ever_detected_fall` 維持原語意（串流結束總結、
`sanity_check` 巡檢抑制都還讀它，行為不變），新增 `fall_display_until` 控制紅框，
採「最後一次觸發後保持 N 秒」（`FALL_DISPLAY_HOLD_SEC`，未設 10 秒）。
不用「只看當下那一幀」是因為偵測逐幀跳動，紅框會閃爍到無法判讀。

### 缺陷二：體角判定只涵蓋一半的躺向（已修）

`body_angle` 是「肩→髖」向量與水平線的夾角，值域 0~180°：站立約 90°、
躺著頭朝右約 0°、**躺著頭朝左約 180°**。原本寫 `body_angle < 40.0`，
**頭朝左那半整個抓不到**。

實測用線上的 `yolo_pose` 對真實串流連續量測，體角一直是 167~177°，
`< 40` 從來沒成立過 —— 該路的臥倒判定其實**全靠長寬比 > 1.25 在撐**，體角形同虛設。

平常被長寬比掩蓋所以看不出來，但「人朝鏡頭方向倒下」時人形框不會變寬，
那時只剩體角能判，會**直接漏報**。改成 `min(a, 180-a) < 40`，門檻沒動。

### 踩到但不是 bug 的一件事：手機方向

手機直立擺放時，Larix 推出來的是「1280x720 橫式框，裡面裝著轉 90° 的畫面」，
而且**沒有旋轉標記**（`stream metadata: {}`），所以下游沒有任何東西能自動修正。
人坐正在影像裡是橫的 → 長寬比 1.56~2.04 → 每一幀都判臥倒。

**系統沒壞，它對「轉了 90 度的輸入」做出了正確判斷**，錯的是輸入。
解法在推流端（Larix 設 Landscape ＋ 手機實體橫擺），不在 AI 端。

⚠️ **查這類問題時的教訓**：一開始查串流解析度是 1280x720（橫式）就判斷「方向沒問題」，
**那個檢查不夠** —— 解析度是橫的不代表畫面內容是正的。要直接把畫面抓出來看。

### 缺陷三：`normal_h_reference` 換來源不重設（**未修，已診斷**）

防線 B（幾何遮擋）用 `normal_h_reference` 記住「這個人站著的正常身高」，之後變矮太多
就判定倒下。但它**只在 worker 開頭 10~40 幀校正一次**，被 `if normal_h_reference is None`
卡住，之後永不更新：

```python
if normal_h_reference is None and frame_count > 10 and frame_count < 40:
    normal_h_reference = h_box
```

實測踩到：worker 啟動時 `cam_in` 還是 `fall-demo.mp4`（1280x720），參考身高從那支影片量。
後來換成 Tapo（640x360），解析度砍半、人的 h_box 只剩 ~175px，比值 ≈ 0.35 遠低於門檻 0.70
→ **每一幀都判「倒下」**。重啟 AI 讓它用當下畫面重新校正，立刻恢復正常。

**會踩到的情境**：換攝影機或調整位置、切換 `stream2`／`stream1`、斷線重連後構圖變了。
只要 worker 沒重啟就一直用舊值，而且症狀是「永遠紅燈」，畫面上完全看不出原因。

修法方向（未做）：重連或畫面尺寸變化時把 `normal_h_reference` 設回 `None` 重新校正。

### 缺陷四：體角判定的前提與實際佈署場景不符（**未修，最需要正視**）

`body_angle < 40 → 臥倒` 這條規則**隱含假設攝影機是大致水平視角**（牆上 2 公尺、微微下傾），
此時「髖在肩下方＝站著」才成立。

Tapo 架高、陡角俯視時實測到的資料（人是**站著**的）：

| 肩中點 | 髖中點 | 水平差 | 垂直差 | 離水平角 |
|---|---|---|---|---|
| (230, 207) | (340, 150) | +120 | **−57** | **27°** |

影像座標 y 往下增加，垂直差 −57 代表**髖部在影像上比肩膀還高**。原因是俯視時「離鏡頭越遠
越靠畫面上方」，站著的人腳比頭遠，於是下半身被投影到上方，軀幹在影像上壓縮成接近水平
——幾何特徵與臥倒完全相同。**系統沒壞，是這個視角下站立的人投影就是接近水平的。**

四道判定在這個視角下的表現：

| 判定 | 結果 | 說明 |
|---|---|---|
| 防線 A・體角 | ❌ 誤報 | 俯角讓軀幹投影接近水平 |
| 防線 A・長寬比 | ⚠️ 邊緣 | 量到 0.95~1.34，門檻 1.25，在門檻上下擺盪 |
| 防線 B・遮擋 | ✅ 正常 | （重新校正後）|
| AcT 時序分類 | ✅ **正確** | 判「正常」信心 0.93~1.00 |

**值得記的結論**：`AcT` 看 30 幀的姿態變化序列、不吃單幀幾何，所以不受俯角影響，
在這次測試中判斷完全正確；反而是兩條手寫的幾何規則被騙。之後要調整權重時這是重要依據。

短期作法：攝影機改成「牆面約 2 公尺高、微微下傾」，不要陡角俯視。
長期方向（屬模型調校，本輪不做）：降低幾何規則權重讓 AcT 主導，或加入攝影機俯角校正。

### 還沒解的：事件一次性閂鎖讓測試很難做

`vlm_triggered` 讓每個 worker 生命週期只發一次事件。這次實測時，AI 啟動 9 秒就被
方向問題誤觸發，把唯一的額度用掉了，導致後面真的躺下**完全不會再發事件**，
一度以為是事件管線壞了。

這強化了第 5 項的必要性，也多了一個原本沒想到的理由：**不解開這個閂鎖，
現場調校與驗收測試幾乎沒辦法做**——每測一次就要重啟一次 AI。

---

## 1.【已完成】S3 上傳接通 —— 前端看得到事發影片了

### 原本卡在哪（記錄用）

舊版這裡寫的是「要去問後端組／AWS 管理者有沒有 `PutObject` 權限」。**這個前提是錯的**：
根 `.env` 早就有一組標明「AWS S3 讀寫」的 `S3_RW_*` 金鑰，只是**全 repo 沒有任何程式碼
讀它**——`ai/inference_test.py` 讀的仍是唯讀那組。真正的缺口是「金鑰名稱對不上」＋
「`CLIP_S3_BUCKET` 沒設」，不是權限。

### 做了什麼

1. **先驗權限再改設定**（順序不能反：設了 bucket 但沒權限＝上傳失敗但壞連結已經發出去，
   比「誠實地沒有影片」更難查）。用 `S3_RW_*` 對 `s3://aipe03-3/videos/` 實跑
   put → head → get → delete，**全通**。
2. `ai/inference_test.py` 的 S3 憑證改成**讀寫優先、舊名 fallback**：
   ```python
   _S3_REGION     = cfg("S3_RW_REGION")            or cfg("S3_REGION")
   _S3_ACCESS_KEY = cfg("S3_RW_ACCESS_KEY_ID")     or cfg("ACCESS_KEY_ID")
   _S3_SECRET_KEY = cfg("S3_RW_SECRET_ACCESS_KEY") or cfg("SECRET_ACCESS_KEY")
   ```
   留 `or` fallback 的原因：沒設 `S3_RW_*` 的機器（Mac、CI）行為與改動前完全一樣。
3. `.env` 補上 `CLIP_S3_BUCKET=aipe03-3` 與 `CLIP_S3_PREFIX=videos`。

### 實測驗證（不是推論）

跑一次真管線觸發跌倒後：

```
🎬 [Room_301_Bed] 事件片段已寫入（187 幀 @ 24.0fps）：ai/clips/clip_Room_301_Bed_20260728_003214.mp4
📦 [Room_301_Bed] 片段已上傳：s3://aipe03-3/videos/clip_Room_301_Bed_20260728_003214.mp4
```

Kafka 上的 payload（`nursing-home-alerts`，欄位一個字沒動）：

```json
{"device_id": 301, "event_type": "fall",
 "clip_path": "s3://aipe03-3/videos/clip_Room_301_Bed_20260728_003214.mp4",
 "detected_at": "...", "snapshot_path": "...", "image_filename": "...",
 "yolo_score": 0.9427, "yolo_threshold": 0.45, "vlm_summary": "..."}
```

用**後端自己的程式碼**（容器內 `core.s3.generate_presigned_url`）換發網址：

```
presigned URL: 已產生
GET → HTTP 200  Content-Type=video/mp4  bytes=995737
非 s3:// 的欄位: None      ← 舊事件（本地路徑）仍照樣回 null，向下相容沒破
```

### 給後端組的名稱清單

| 項目 | 值／名稱 | 後端要做什麼 |
|---|---|---|
| bucket / prefix | `aipe03-3` / `videos/` | — |
| **後端讀的憑證變數（不動）** | `S3_REGION`、`ACCESS_KEY_ID`、`SECRET_ACCESS_KEY` | 維持唯讀，一行不改 |
| AI 端改讀的憑證變數 | `S3_RW_REGION`、`S3_RW_ACCESS_KEY_ID`、`S3_RW_SECRET_ACCESS_KEY` | 僅告知 |
| 契約欄位 `clip_path` 的值 | 由本地路徑改成 `s3://aipe03-3/videos/clip_<camera>_<ts>.mp4`（**欄位名不變**）| 僅告知；`GET /events/{id}/media` 從此會回真的 presigned URL |
| 唯讀金鑰的 `GetObject` 權限 | 已用後端自己的程式碼實測 HTTP 200 | ✅ **不需要任何動作，已確認可用** |
| `event_type` 值域 | 從此恆為 `"fall"`（`chair_slip` 不再出現，型別仍是字串）| 僅告知 |
| 後端 log 的 422 毒訊息 | `agitation` / `bed_exit` / `wandering` 事件源已刪，不再進 Kafka | 僅告知，會自然消失 |

**兩組金鑰刻意分開＝最小權限**：AI 端上傳片段要 `PutObject`，後端簽 presigned URL 只要
`GetObject`。不要把讀寫金鑰塞進後端那三個名字。

### 已知殘留

- 慢車道（`nursing-home-alerts`）的事件要 `ai/vlm_worker.py` 在跑才會轉進後端。
  驗證當下 vlm_worker 沒開，所以那筆事件停在 Kafka、沒進 DB —— 這是既有行為、不是這次的迴歸。
- 片段每個 worker 生命週期只錄一次（掛在 `vlm_triggered` 一次性閂鎖下），要等第 5 項的
  冷卻計時器才會解開。

### 片段錄製本身的設計理由（原 `HANDOVER.md`，2026-07-30 併入）

原本有一份 272 行的 `HANDOVER.md` 專門記這件事，但它寫於「S3 權限還沒確認」的時期，
大半內容已被上面幾節取代，其中「上傳憑證沿用後端那三個名字」那句**現在是錯的**
（正確做法見 [`../CLAUDE.md`](../CLAUDE.md) 第三節：AI 端用 `S3_RW_*`，兩組刻意分開）。
故整份刪除，只留下這幾條**至今仍成立、且別處沒記**的設計理由：

| # | 決定 | 理由 |
|---|---|---|
| 1 | 緩衝存**原始幀**，位置在**跳幀之前** | worker 有 `frame_count % 2` 隔幀跳過。緩衝擺在跳幀之後的話，5 秒只會收到 2.5 秒份量，片段的時間軸整個對不上 |
| 2 | 片段**不畫** AI 標註框 | 不受 `NO_RENDER=1` 影響、不必為每個緩衝幀多跑一次 `.plot()`；而且被跳過的幀根本沒有推論結果可畫，硬要畫會錄出一閃一閃的框。**這點後來升格成組長決策**，見第 8 項 |
| 3 | 警報**立刻發**，片段稍後落地 | 跌倒是急救場景，為了等影片讓警報延遲 5 秒以上不划算。護理師從收到警報到點開影片本來就不只 5 秒 |
| 4 | 用 `cv2.VideoWriter`，不用 ffmpeg pipe | 跟著 `opencv-python` 走，不需要外部 ffmpeg 執行檔，三個平台都能跑 |
| 5 | 緩衝**獨立降寬**到 `CLIP_WIDTH` | 1080p 全解析度下前後 10 秒每台相機約 1.8GB，多路併發直接 OOM。推論吃的仍是原圖，完全不受影響 |

**最值得留的一段 —— 上游那個「拼出來是後 5 秒 ×2」的 bug**：

上游的 `pre_video_buffer` 每幀都在滾動，但**收工當下才去取它**：

```python
full_10_sec_frames = list(pre_video_buffer) + post_video_buffer   # ← 這裡
```

等後段錄滿 5 秒，那個環形緩衝裡裝的已經正好是**後段那批幀**，前 5 秒整段遺失。
本實作改成**觸發當下就對前段緩衝拍快照**，收工時用快照拼接。模擬驗證
（30fps、第 400 幀觸發、前後各 5 秒）：

```
[本實作] 幀數=300 範圍=251..550 ✅ 時間軸正確
[上游]   幀數=300 範圍=401..550 ❌ 重複 150 幀
```

**這個 bug 錄出來的檔案長度正確、播得動、不報錯**，只有把畫面調出來看才知道前半段是假的。

---

## 2.【已完成】六大防線收斂為「跌倒 + 巡檢」，並立了 `ai/modules/` 白名單

### 決定

`ai/modules/` **只保留 `__init__.py` 與 `sanity_check.py`**，其餘不使用也不套用。
刪除五個模組：`bed_exit.py`（A 離床）、`wandering.py`（E 遊走）、`micro_motion.py`（F 躁動）、
`audio_fusion.py`（H 音訊融合）、`chair_slip.py`（I 座椅滑落）。

### 這一刀同時解掉了舊版第 3 項的「契約破口」

舊版列的三個「自組 payload 被後端 422 丟棄」的破口（`micro_motion` / `wandering` /
`bed_exit`）**是從根拔除，不是逐一修補**——製造破口的程式碼整個不在了。

`sanity_check.py` 走的是 `nursing-home-alerts`，會先經 `vlm_worker` 重新組包成 7 欄外發，
所以它多帶的 `alert_id` / `camera_id` / `severity` / `status` 到不了後端，**不會 422**。
`severity: "low"` 是後端 2026-07-19 移除該欄位後的殘留，無害，故不修（它是白名單檔，
維持一行不動）。

### 跌倒偵測沒有被削弱

跌倒主邏輯一直都在 `ai/inference_test.py` 的 `camera_worker` 主迴圈（防線 A 肩髖體角 +
長寬比、防線 B 幾何遮擋、AcT 30 幀時序分類），**從來就不在 `modules/` 底下**。

反而是**移除了一個誤報來源**：`audio_fusion.py` 對 camera_id 含 `"303"` 的相機
**每 22 秒隨機**丟出 `THUD_CRASH`/`HELP_SCREAM`，並把信心強制拉到 `0.96` 直入快速道。
那是展示用的假資料產生器，不是偵測能力。

### 三個行為變更（要記得）

1. **`event_type` 從此恆為 `"fall"`**，`"chair_slip"` 不再出現。後端與 agent 都當字串
   處理（非 enum），不會 422。`agent/schemas.py` 的格式說明註解已同步更新。
   **payload 欄位一個字沒動**，護欄 AST 契約檢查全綠。
2. **快速道條件簡化**為 `act_confidence >= 0.90 且非遮擋`（原本多一個「或明確 chair_slip」）。
3. **巡檢間隔從 15 秒改成 60 秒**。原本 `sanity_check` 靠
   `not is_leaving_bed and not is_wandering` 兩個旗標抑制，那兩個模組刪掉後旗標恆為 False，
   等於少了兩道閘門；而 `uncertainty_router` 是「一律二審不加 discard」、`vlm_worker`
   每筆二審完成都外發，維持 15 秒的話後端會每 15 秒多一筆巡檢事件。
   間隔可用 `SANITY_INTERVAL_SEC` 調（未設＝60），**改的是呼叫端，`sanity_check.py` 沒動**。

### 規則落地：文件 + 機器都擋

- **根目錄新增 [`CLAUDE.md`](../CLAUDE.md)** —— 每次動工前必讀，寫明白名單、理由、
  跌倒主邏輯在哪、以及「真的要復活」的流程。
- **[`CONTRIBUTING.md`](../CONTRIBUTING.md) 第六節**加一條紅線，與 Kafka topic、
  `route_by_confidence()` payload 並列。
- **[`scripts/check_guardrails.py`](../scripts/check_guardrails.py) 加 `check_module_whitelist()`**
  —— AST 靜態解析，擋兩種違規：在 `ai/modules/` 新增非白名單檔案、任何 `.py` import
  非白名單模組。pre-commit 與 GitHub Actions 兩層都會紅燈。

  為什麼一定要機器擋：這種「模組自己送 Kafka」的破口靠 code review 抓不到——它跑得動、
  不噴錯，只是訊息在後端被靜默丟掉，要跑夠長的影片才會曝露（舊版用 7~9 秒的
  test1/2/3 測了很久都沒發現，換 4.9 分鐘的 test4.mp4 才炸出來）。

  兩種違規都已用負向測試確認**擋得下來**。

### 真的要復活某個模組時

三件事缺一不可，不要只改護欄讓它過：改 `CLAUDE.md` 白名單並寫清楚為什麼收回這個決定 →
改 `scripts/check_guardrails.py` 的 `MODULES_ALLOW` → **先補契約測試**，確認該模組
不自組 payload 外發，外發一律回主迴圈的 `route_by_confidence()`。

---

## 3.【已完成】Triton GPU vs CPU 同機對照

完整報告：**[`ai/BENCHMARK_GPU_VS_CPU.md`](../ai/BENCHMARK_GPU_VS_CPU.md)**。摘要：

| | GPU | CPU | 倍數 |
|---|---:|---:|---:|
| 端到端 processed FPS（單路）| **10.8 fps** | **3.2 fps** | 3.4× |
| `yolo_pose`（ONNX 兩邊同款）| 22.5 ms | 76.1 ms | 3.4× |
| `rt_detr`（GPU TensorRT vs CPU ONNX）| 17.3 ms | 192.0 ms | 11.1× |
| `action_transformer` | 2.08 ms | **0.78 ms** | **0.4×（CPU 較快）** |

三個值得記住的結論：

1. **瓶頸是 `rt_detr` 不是 pose**。CPU 上單次 192 ms，占端到端每幀時間的絕大部分。
2. **`action_transformer` 在 CPU 上比 GPU 快**——模型只有 315 KB，GPU 的 kernel 啟動與
   PCIe 搬運比算它本身還貴。之後要做混合部署的話，這顆放 CPU 是划算的。
3. **TensorRT 是真的有用**：同在 GPU 上，`rt_detr` 用 TensorRT plan 比用 ONNX 快 1.7 倍。

**新工具**（都走環境變數，未設時行為與改動前位元級相同）：
- `ai/run_triton.sh` 新增 `TRITON_GPUS`（設 `none` 就不帶 `--gpus`）、`TRITON_CPUS`
  （`--cpuset-cpus`）、`LOAD_MODELS`（原本硬編三顆模型名）
- `ai/make_cpu_repo.sh` —— 產生 CPU 版 model repository（config 改 `KIND_CPU`、
  權重用 hardlink 零額外空間）
- `ai/bench_triton.py` —— 復用線上的三支 Triton client 量測，同時抓 Triton `/metrics`
  分離出 server 端純推論時間

**下一步的明顯空間**（本輪沒做）：四顆 config 全是 `max_batch_size: 0` + `count: 1`，
等於 **dynamic batching 與多 instance 兩項都沒開**。要上多路相機，這是優先於任何
模型替換的事。

---
## 6.【已完成】agent P2：後端記錄 AI 判斷 + 前端顯示建議

分支 `feat/agent-p2-ai-verdict`，PR #14，已合併進 `test/main-integration`
（merge commit `23eeec9`，commits `cf2e973` + `441c0d1`）。

### 範圍（照原計畫拍板：只做 P2 的「A 層」，沒做 cutover）

- **沒有**停掉現行 `uncertainty_router.py`／`vlm_worker.py`，agent 仍是 shadow
  （`AGENT_SHADOW=1` 沒動），現行資料流沒變。
- 只做了「後端記錄 + 前端顯示」，AI 判斷是人工複判的**參考資訊**，不接手決策權。

### 做了什麼

| 任務 | 內容 |
|---|---|
| 後端欄位 | `DetectEvent`（`backend/core/models.py`）加 `ai_verdict`／`ai_confidence`／`ai_reasoning`，皆 optional，獨立於人工 `verdict`；`EventCreateRequest`、`serialize_event` 同步加 |
| DB 遷移 | 正式 RDS 已有既有資料（`create_all` 不會回頭補欄位），`core/database.py` 加回 `run_column_migrations()`（`ALTER TABLE ADD COLUMN IF NOT EXISTS`），`main.py`／`init_db.py` 都會呼叫 |
| 後端護欄 | 確認 `PATCH /events/{id}/verdict` 完全不碰 `ai_*` 欄位，沒有任何自動關閉事件的路徑；`false_alarm` 只存建議，關閉事件仍要人工按「確認誤報」 |
| 前端顯示 | 新增 `AiSuggestionBadge` 元件；**事件中心列表**（`EventCenterUnresolved.tsx`）與**詳情頁**都顯示徽章 + `ai_reasoning`；`ai_verdict=false_alarm` 時附「確認誤報」一鍵鈕，走既有 verdict 端點 |
| 測試 | 後端補 `true_alarm`／`false_alarm`／`null` 三路徑 + 舊格式相容測試，149 個 pytest 全過 |

### 實測驗證（不是推論）

拉一組拋棄式 Postgres + 這個分支的程式碼，完整模擬「正式 RDS 現況」跑過一次
migration，確認 `ALTER TABLE` 語法在真正的 PostgreSQL 上沒問題；再用 Playwright
實際開瀏覽器登入、確認事件中心列表與詳情頁的徽章、按鈕、點擊後的狀態轉換都正確。
全程沒有觸碰正在服務中的 `nh-backend`／`nh-frontend` 與正式資料庫。

也用真實 Ollama VLM 對 `ai/snapshots/` 裡的真實截圖跑過多輪判讀，把結果送進拋棄式
後端驗證整條「VLM 判斷 → 存 DB → 前端顯示」的資料管線，不是塞假資料裝樣子。

### 過程中額外修的問題：VLM 隨機拒答

驗證時發現 `llava:latest` 對**同一張圖、同一個 prompt**，在預設溫度下有機率隨機
回「無法看到圖片」之類的拒答（甚至答錯語言，測到一次葡萄牙文），技術上呼叫成功、
內容非空，但語意上等於沒判讀，且不會觸發原本的重試機制。已修：

- `agent/config.py` 新增 `vlm_temperature`（`AGENT_VLM_TEMPERATURE`，預設 `0.1`）
- `agent/nodes/vlm.py` 呼叫時帶入溫度；新增拒答關鍵字偵測，命中就當 `VlmError`
  觸發既有重試政策
- agent 全部 181 個 pytest 通過

**這個修復解決的是「模型隨機罷工」，不是「姿態判讀準不準」**——後者本來就不是
VLM 該扛的責任：`agent/nodes/vlm.py` 的既有註解就寫明「單張靜態畫面分不出躺著
休息與跌倒，時序才是關鍵」，真正的姿態判斷是防線 A（`yolo_pose` 幾何計算肩髖
體角）+ AcT 時序分類；VLM 二審只負責抓明顯誤判線索（沒人／物品掉落），設計上
就不指望它精準判讀姿態細節。用系統正式 prompt 重測同一張圖，即使套用溫度+拒答
修復，姿態描述仍會前後矛盾，證實這是模型能力上限，不是可調參數解決的。

### 已知殘留

- VLM 目前測試都只餵單張靜態截圖；`agent/nodes/vlm.py` 其實已支援多張連續畫面
  輸入（`image_paths`），理論上能顯著改善姿態判讀準確度，但這次沒有實際驗證
  多圖模式的效果，留給後續。
- `ai/snapshots/` 目錄裡有大量重複／來源不明的圖片（用 md5 比對 47 個檔案只有
  14 種真正不同內容，部分內容明顯不是這系統自己相機拍的）。不影響功能，但之後
  要挑「乾淨」的展示或測試用截圖時，這個目錄不能照單全收，要先看過內容再選。
- agent 真正即時串接寫進 DB（而非只寫 `ai/agent_shadow.jsonl` shadow log）
  是另一個小任務，這輪只驗證了「手動把 shadow 產出的判斷塞進資料庫、前端正確
  顯示」這條路徑。

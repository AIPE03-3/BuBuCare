# inference_test FPS 量測與提速筆記（stage2，本地端 RTX 5060 Ti + Triton）

本檔記錄在**本地端 GPU（Triton）** 上對 `inference_test.py` 做的 FPS 量測、提速實驗與瓶頸剖析。
量測用長片 `ai/test_demo/test4.mp4`（4.9 分鐘、1080p、24fps），單路、無節流。

## 量測開關（皆環境變數，未設＝原行為，不影響推論邏輯與契約）

| 變數 | 作用 |
|---|---|
| `FPS_LOG_EVERY=N` | 每處理 N 幀印一次區間/累計實測 FPS（預設 60）|
| `FPS_NO_THROTTLE=1` | 略過貼齊 source-fps 的節流睡眠，量純 GPU 吞吐上限 |
| `SINGLE_SOURCE=<檔案\|rtsp URL>` | 只掛一路（避免多路併發稀釋單路數字）|
| `NO_RENDER=1` | 跳過 Step D 純畫圖渲染（`.plot()`/mask 疊圖/`putText`/`copy`），HEADLESS 壓測用；快照存檔仍保留 |
| `DETR_EVERY_N=N` | rt_detr 環境物件偵測降頻成「每 N 個處理幀跑一次」，其餘幀復用上次結果（預設 1＝每幀＝原行為）|
| `DECODE_PREFETCH=1` | 解碼移到背景執行緒預讀（與推論重疊），未設＝原本序列解碼 |

## Triton client：HTTP vs gRPC

client（`triton_*_client.py`）用 ultralytics `TritonRemoteModel`，**原生支援 gRPC**，切換只需改 URL scheme、**不動任何程式碼**：

```bash
# HTTP（Triton :8010）
export TRITON_POSE_URL=http://127.0.0.1:8010/yolo_pose   # detr/act 同理

# gRPC（Triton :8011）—— 需 venv 裝 gRPC 支援：pip install "tritonclient[grpc]"
export TRITON_POSE_URL=grpc://127.0.0.1:8011/yolo_pose
export TRITON_DETR_URL=grpc://127.0.0.1:8011/rt_detr
export TRITON_ACT_URL=grpc://127.0.0.1:8011/action_transformer
```

> `tritonclient[grpc]` 會把 `protobuf` 由 7.x 降到 6.x；已驗 kafka/ultralytics/cv2/torch/av/langgraph 皆正常 import。

典型跑法（單路、gRPC、無節流、壓測）：
```bash
TRITON_POSE_URL=grpc://127.0.0.1:8011/yolo_pose \
TRITON_DETR_URL=grpc://127.0.0.1:8011/rt_detr \
TRITON_ACT_URL=grpc://127.0.0.1:8011/action_transformer \
HEADLESS=1 SINGLE_SOURCE=ai/test_demo/test4.mp4 FPS_NO_THROTTLE=1 NO_RENDER=1 \
python ai/inference_test.py
```

## 實測結果與瓶頸剖析（重點）

| 設定 | FPS |
|---|---|
| 基準 HTTP | ~11.0 |
| gRPC | ~11.5（+4%）|
| gRPC + `NO_RENDER` | ~12.5（+14%）|
| MediaMTX RTSP 鏈路 | ~11.3（串流本身幾乎不吃 FPS）|
| gRPC + `NO_RENDER` + `DETR_EVERY_N=10`（stage3）| 14.0 |
| ↑ 再加 `DECODE_PREFETCH=1`（stage3）| **15.6** ✅ 過 30fps 攝影機門檻 |

> 註：stage3 重測時「gRPC + `NO_RENDER`」基準量到 **12.0**（stage2 記的是 ~12.5）；
> 機器負載不同會有 ±0.5 fps 波動，比較增益時請以**同一輪的基準**為準，別跨 stage 直接相減。

**逐段剖析（每幀，gRPC）**：

| 階段 | ms/幀 | 佔比 |
|---|---|---|
| **pose（client 端後處理）** | 23.6 | **50%** |
| **detr（client 端後處理）** | 13.9 | 30% |
| decode（PyAV） | 6.9 | 15% |
| plot（畫圖） | 2.4 | 5% |

> stage3 起 detr 那 13.9ms 被 `DETR_EVERY_N` 攤平成 **13.9/N**（N=10 → 1.4ms），
> 剩下 pose 的 23.6ms 成為最大單項。

**結論**：純三顆 Triton GPU 推論僅 25.4ms（理論 39fps），GPU 不是瓶頸。實跑卡在
~11fps 的主因是 **pose/detr 的 client 端 CPU 後處理**（letterbox / NMS / `scale_coords` /
tensor 轉換），佔幀時間 ~80%。故 gRPC、源頭降解析度、關畫圖這類「通用提速清單」在此
效果都有限（各 0～1.5 fps）；真正該打的是**把 pose/detr 的後處理搬到 GPU（CUDA）**——見下。

## 已驗證有效 / 無效的提速項

- ✅ **gRPC**：+0.5 fps。小，但零成本（只改 env），建議壓測時採用。
- ✅ **`NO_RENDER`**：+1 fps。HEADLESS 壓測時該開。
- ⭕ **源頭降解析度**：實測 ≈0（甚至略降，多一次 resize 抵銷）。已不保留此開關。
- ✅ **detr 降頻 `DETR_EVERY_N`（stage3）**：**+2.0 fps（12.0 → 14.0，+17%）**。詳見下一節。
- ✅ **decode 並行 `DECODE_PREFETCH`（stage3）**：**+1.6 fps（14.0 → 15.6）**，且**行為零位移**。詳見下下節。
- ⭕ **pose 後處理搬 GPU（選項 C，已試、已還原）**：反而略降（~11.6 vs 12.5）。
  原因：conf 過濾後通常只剩 1 個人，NMS/scale 是在 1 row 上做，這麼小的運算搬 GPU，
  CPU→GPU 傳輸＋kernel 啟動的固定開銷 > 省下的運算。剖析裡 pose 那 23.6ms 大頭其實是
  `torch.from_numpy(8400×56)` 搬運與 gRPC 回傳，不是 NMS 本身。**小批量/單人 workload
  上，後處理搬 GPU 是負優化**。已還原成 CPU 版（正確性驗過 GPU/CPU 輸出一致，max|Δ|<1e-3px）。

## detr 降頻（`DETR_EVERY_N`）—— stage3

### 為什麼可以降頻

rt_detr 佔 **13.9 ms/幀（30% 幀時間）**，但它偵測的**全是靜態家具**
（`inference_test.py` 寫死清單 `["wheelchair","bed","chair","couch","bottle","cup"]`）。
`results_env` 的三個下游用途都只是**空間參考框**，不是逐幀語意：

| 用途 | 位置 |
|---|---|
| `bed_box_xyxy` → 模組 A 離床 | `inference_test.py` |
| `chair_box` → 模組 I 座椅滑落 | `modules/chair_slip.py` |
| mask 疊圖 | `inference_test.py`（RT-DETR 輸出只有 output0、無 proto/mask，此段實際恆不執行）|

家具不會動，幾秒不更新沒差。**pose 則必須每幀跑**（要餵連續 30 幀 window 給 Action
Transformer，時序不能有洞），所以只降 detr、不動 pose。

### 關鍵實作：降頻 ≠ 傳 None

跳過的幀**復用 worker 內快取的上次 `results_env`**，不是塞 None。傳 None 會讓
`chair_slip` / 離床在跳過的幀拿不到參考框，偵測變成時斷時續。家具靜態，復用才正確。
另外 **Triton 斷線降級時的 `results_env = None` 會一併寫回快取**——斷線就該讓下游看到
None，不能拿幾幀前的舊框假裝偵測還活著。`N=1`（未設）時走的是與原本一字不差的路徑。

### 實測（同 gRPC + `SINGLE_SOURCE=test4.mp4` + `FPS_NO_THROTTLE` + `NO_RENDER`）

| 設定 | fps | ms/幀 | 增益 | 模組 I 觸發次數 |
|---|---|---|---|---|
| 基準（未設） | **12.0** | 83.3 | — | 5 |
| `DETR_EVERY_N=5` | 13.4 | 74.6 | +11.7% | 3 |
| **`DETR_EVERY_N=10`（採用）** | **14.0** | **71.4** | **+16.7%** | 3 |
| `DETR_EVERY_N=15` | 13.7 | 73.0 | +14.2% | **1** ⚠️ |

四輪皆 0 traceback、0 推論失敗，主迴圈事件都照常外發（欄位組合完全一致）。

**選 N=10 的理由**：曲線在 N≈10 飽和（10↔15 差異落在 ±0.4 fps 量測噪音內），而 N=15 沒
更快、模組 I 卻掉到只觸發 1 次（框太舊、偵測器幾乎不再 re-arm），是明確劣化。N=5 與
N=10 的正確性表現相同但較慢，故取 N=10。

### ⚠️ 天花板：detr 降頻**到不了 16~18 fps**

基準 83.3 ms/幀，detr 只佔 13.9 ms。**就算 N=∞ 完全不跑 detr，上限也只有
83.3 − 13.9 = 69.4 ms → 14.4 fps**。N=10 實測 14.0 已經吃掉這條路 **90%** 的可得增益
（理論 70.8ms/14.1fps，與實測吻合）。

要接真實 30fps 攝影機（需 15 處理幀/秒）**還差最後 1 fps，這條路給不了**。**別再往 detr
這條路挖了**——最後那 1 fps 由下一節的 `DECODE_PREFETCH` 補上。

> ### 📌 教訓：算佔比要看清楚分母
>
> 這輪原本的目標訂在 16~18 fps，是因為把上面剖析表的「detr 佔 30%」讀成「佔一整幀的 30%」。
> 但那張表的佔比欄是**佔已剖析的 46.8ms 的比例**，不是佔一整幀 83.3ms 的比例——中間
> 差的 36.5ms（等 Triton GPU 來回 25.4ms ＋ Kafka/雜項 ~11ms）沒被列進表裡。
>
> ```
> 誤以為： 13.9 / 46.8 = 30%  → 砍掉可到 83.3×0.7 = 58.3ms = 17.1 fps（＝當初訂的目標）
> 實際上： 13.9 / 83.3 = 17%  → 砍掉只到 83.3−13.9 = 69.4ms = 14.4 fps（＝真天花板）
> ```
>
> **動手前先用「ms/幀」把整幀預算列平**，別直接引用舊表的百分比。另外 fps 是倒數，
> 省同樣的 ms 在越高 fps 時效果越差，**永遠用 ms/幀 思考、最後才換算 fps**。

### ⚠️ 提速會位移邊緣觸發偵測器（每次動 FPS 都要重跑正確性驗證）

detr 降頻不是零影響。哪些幀拿到哪個框改變後，edge-triggered 的偵測器觸發時機會位移：

| | 基準 | N=10 |
|---|---|---|
| 模組 I 座椅滑落觸發次數 | 5 | 3 |
| 模組 A 離床事件 | 0 | 1 |

事件**照樣會發、沒有 None 崩潰**（驗收條件已過），但「觸發幾次、第幾秒觸發」會變。
模組 I 由 5 降到 3 是因為快取讓 `chair_box` 更穩定存在，`chair_slip.py` 的
`else: self.slip_triggered = False` 重置分支較少被打到——少抖動其實較好，但確實是行為差異。
**後續改併發也會再位移一次，所以每次動 FPS 都要重跑這組正確性驗證，別預設「只是提速、不會怎樣」。**

正確性驗證跑法：`DETR_EVERY_N=10` 加上述壓測開關跑完整支 test4.mp4，檢查
(1) log 有「偵測到長輩從座椅滑落」(2) 無 traceback (3) Kafka 主迴圈事件欄位組合不變。

## decode 並行（`DECODE_PREFETCH`）—— stage3

### 為什麼有效

camera_worker 原本是「讀一幀 → 推論 → 讀下一幀 → 推論」**完全序列**：解碼那 ~6.9ms
期間 GPU 在乾等，推論那 ~64ms 期間解碼器也在乾等。兩件事根本不互相依賴，卻排隊做。

`DECODE_PREFETCH=1` 在 `av_reader.open_source()` 外包一層 `PrefetchReader`：一條背景
執行緒預先解好下一幀塞進 `queue.Queue(maxsize=2)`，主迴圈 `read()` 直接取，解碼時間
整個藏進推論時間裡。

### 實作要點

- **inner reader 必須在背景執行緒內建立**：PyAV 的 container 與 `decode()` 迭代器綁
  建立它的執行緒，所以 `PrefetchReader` 收的是 **factory** 而不是建好的 reader。
- **fps 在背景執行緒起手時抄成 float**，`get(CAP_PROP_FPS)` 回快取值，主執行緒完全
  不跨執行緒碰 PyAV 物件。
- **EOF 用哨兵物件**傳遞，`read()` 在 EOF 後恆回 `(False, None)` 不卡住。
- **`release()` 會先清空 queue** 再 join，讓可能卡在滿 queue `put()` 上的背景執行緒能退出。
- queue 只留 2 格：對影片檔衝吞吐，對 RTSP 最多多 2 幀延遲（~66ms@30fps）；即時流
  若消費不贏來源，單執行緒版本本來也一樣落後，故無退步。

### 實測

| 設定 | fps | ms/幀 |
|---|---|---|
| `DETR_EVERY_N=10` | 14.0 | 71.4 |
| **＋`DECODE_PREFETCH=1`（採用）** | **15.6** | **64.1** |

省下 7.3ms，與純解碼實測（7086 幀 / 51.3s ＝ **7.2ms/幀**）幾乎完全吻合——代表解碼
時間確實被 100% 藏進推論裡了。

### ✅ 這一步行為零位移

不像 detr 降頻，`DECODE_PREFETCH` **只改「幀什麼時候被解碼」，不改「哪些幀被處理」**，
所以偵測結果完全一致：

| | `DETR_EVERY_N=10` | ＋`DECODE_PREFETCH=1` |
|---|---|---|
| 模組 I 座椅滑落 | 3 | 3 |
| 模組 F 躁動 | 6 | 6 |
| Kafka 事件 | 1 主迴圈 + 7 模組 | 1 主迴圈 + 7 模組 |
| traceback | 0 | 0 |

## 收斂結論

在**單路、單人**的長照場景下，這條管線卡在 **Python 單執行緒逐幀 CPU 後處理 + gRPC
回傳搬運**，且量體太小、搬 GPU 不划算。

**目前建議的上線組合（stage3）**：

```bash
TRITON_POSE_URL=grpc://127.0.0.1:8011/yolo_pose \
TRITON_DETR_URL=grpc://127.0.0.1:8011/rt_detr \
TRITON_ACT_URL=grpc://127.0.0.1:8011/action_transformer \
DETR_EVERY_N=10 DECODE_PREFETCH=1 NO_RENDER=1 \
python ai/inference_test.py
```

＝ **15.6 fps（64.1 ms/幀）**，**已過接真實 30fps 攝影機所需的 15 處理幀/秒門檻。**
（`NO_RENDER` 只在不看畫面時開；要 GUI 就拿掉，約 −1 fps。）

演進：12.0（stage2 基準）→ 14.0（detr 降頻）→ **15.6**（decode 並行）。

### 還想更快的話

剩下 64.1ms 的組成大致是：等 Triton GPU 來回 ~25.4ms、pose client 後處理 23.6ms、
detr 攤平後 1.4ms、雜項 ~14ms。能打的只剩：

1. **減少 pose 的回傳搬運量**（最大單項，估 +3~5 fps）：那 23.6ms 的大頭**不是 NMS 運算**，
   是 Triton 回傳 8400×56 原始 tensor（~1.9MB/幀）經 gRPC ＋ `torch.from_numpy` 搬運，
   而 conf 過濾後通常只剩 1 個人。作法是讓 **Triton 端**就過濾完、只回傳存活的幾 row
   （export 時 `nms=True`，或加 python backend / ensemble）。
   ⚠️ **這跟 stage2 已驗證負優化的「選項 C」不同**：選項 C 是在 *client 端*把 NMS 搬 GPU 算，
   資料照樣搬了 1.9MB 過來 → 負優化；這裡打的是**搬運量本身**。
   ⚠️ 風險中高：keypoints 有偏差會直接毒到 AcT 的 30 幀 window，**務必逐幀比對新舊輸出
   `max|Δ| < 1e-3 px`** 再上（比照 stage2 驗選項 C 的做法）。
2. **每相機獨立進程繞開 GIL**：對**多路併發**吞吐有效，對**單路** fps 沒幫助。
3. ~~三顆模型並行打~~：**已無價值，別花時間**。AcT 必須等 pose 算完（要 keypoints 才能組
   window）不能並行；能並行的只有 pose ∥ detr，而 detr 現在只跑 1/10 幀，收益已被
   `DETR_EVERY_N` 提前吃掉。

### ⚠️ 不建議的假捷徑：改跳幀比例

把 `inference_test.py` 的 `frame_count % 2` 改成 `% 3`，30fps 攝影機就只需 10 處理幀/秒，
現有數字立刻「達標」。**但這是改模型行為、不是提速**：AcT 的 30 幀 window 會從涵蓋 2 秒
變成 3 秒，和訓練時的時間尺度不一致，跌倒判斷準確率會受影響。真要走得重訓 AcT 或至少
重跑完整召回率評估。

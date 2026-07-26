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
| gRPC + `NO_RENDER` + `DETR_EVERY_N=10`（stage3）| **14.0** |

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

要接真實 30fps 攝影機（需 15 處理幀/秒）**還差最後 1 fps，這條路給不了**。剩下的只能從
pose 那 23.6 ms 或**併發**拿——見下方收斂結論。**別再往 detr 這條路挖了。**

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

## 收斂結論

在**單路、單人**的長照場景下，這條管線卡在 **Python 單執行緒逐幀 CPU 後處理 + gRPC
回傳搬運**，且量體太小、搬 GPU 不划算。目前的最佳組合是
**gRPC + `NO_RENDER` + `DETR_EVERY_N=10`** ＝ **14.0 fps**（stage3）。

**還差最後 1 fps，而且已知的「省呼叫」路數用完了。** 接真實 30fps 攝影機需要 15 處理幀/秒；
detr 降頻的天花板是 14.4 fps（見上節），已經吃到 14.0。剩下能打的只有：

1. **併發**：三顆模型並行打（序列 25ms → ~14ms），或每相機獨立進程繞開 GIL。
2. **pose 後處理**那 23.6ms——但**別再試「搬 GPU」**（選項 C 已驗證是負優化）；
   真正的大頭是 `torch.from_numpy(8400×56)` 搬運與 gRPC 回傳，要打就打「減少搬運量」
   （例如讓 Triton 端就做完 conf 過濾，只回傳少數 row）。

兩者都是較大改動，且會再次位移邊緣觸發偵測器的時機，動之前先讀上節的正確性驗證要求。

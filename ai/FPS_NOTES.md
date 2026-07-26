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

**逐段剖析（每幀，gRPC）**：

| 階段 | ms/幀 | 佔比 |
|---|---|---|
| **pose（client 端後處理）** | 23.6 | **50%** |
| **detr（client 端後處理）** | 13.9 | 30% |
| decode（PyAV） | 6.9 | 15% |
| plot（畫圖） | 2.4 | 5% |

**結論**：純三顆 Triton GPU 推論僅 25.4ms（理論 39fps），GPU 不是瓶頸。實跑卡在
~11fps 的主因是 **pose/detr 的 client 端 CPU 後處理**（letterbox / NMS / `scale_coords` /
tensor 轉換），佔幀時間 ~80%。故 gRPC、源頭降解析度、關畫圖這類「通用提速清單」在此
效果都有限（各 0～1.5 fps）；真正該打的是**把 pose/detr 的後處理搬到 GPU（CUDA）**——見下。

## 已驗證有效 / 無效的提速項

- ✅ **gRPC**：+0.5 fps。小，但零成本（只改 env），建議壓測時採用。
- ✅ **`NO_RENDER`**：+1 fps。HEADLESS 壓測時該開。
- ⭕ **源頭降解析度**：實測 ≈0（甚至略降，多一次 resize 抵銷）。已不保留此開關。
- ⭕ **pose 後處理搬 GPU（選項 C，已試、已還原）**：反而略降（~11.6 vs 12.5）。
  原因：conf 過濾後通常只剩 1 個人，NMS/scale 是在 1 row 上做，這麼小的運算搬 GPU，
  CPU→GPU 傳輸＋kernel 啟動的固定開銷 > 省下的運算。剖析裡 pose 那 23.6ms 大頭其實是
  `torch.from_numpy(8400×56)` 搬運與 gRPC 回傳，不是 NMS 本身。**小批量/單人 workload
  上，後處理搬 GPU 是負優化**。已還原成 CPU 版（正確性驗過 GPU/CPU 輸出一致，max|Δ|<1e-3px）。

## 收斂結論

在**單路、單人**的長照場景下，這條管線的 FPS 上限（~12.5fps）主要卡在
**Python 單執行緒逐幀 CPU 後處理 + gRPC 回傳搬運**，且量體太小、搬 GPU 不划算。
零成本可採用的是 **gRPC + `NO_RENDER`**（~12.5fps）。若要再往上，方向不是「單幀搬 GPU」，
而是**併發**：三顆模型並行打（序列 25ms → ~14ms）、或每相機獨立進程繞開 GIL——
這些是後續有需要再做的較大改動，非本輪範圍。

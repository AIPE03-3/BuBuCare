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
- 🎯 **client 後處理搬 GPU（進行中）**：剖析指向的真正大魚，見 `triton_pose_client.py` /
  `triton_detr_client.py` 的 `_postprocess`（NMS/scale 改在 CUDA tensor 上做）。

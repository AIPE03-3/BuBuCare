# `docs/legacy/` — 從 `albert_chiang` 分支保存下來的檔案

這裡的檔案來自 **`albert_chiang` 分支**（來源 commit `2097fcb`，2026-08-01，作者 Albert）。
該分支上有 72 個未合併進 `main` 的 commit，全部是 Albert 一人的工作成果。

分支本身因為含有硬編碼的憑證與大量訓練用快照而不宜保留，
但其中幾個檔案記錄了本專案技術選型過程中**評估過、最終沒有採用**的方案。
這些方案的存在本身就是設計決策的一部分，所以在刪除分支前先保存於此。

**這些檔案僅供查閱，不參與建置，也不被任何程式碼引用。**

---

## 檔案來源與保存理由

| 檔案 | 原始路徑 | 為什麼保存 |
|---|---|---|
| [`deepstream_app_config.txt`](deepstream_app_config.txt) | `deepstream_configs/` | DeepStream 7.0 的完整 pipeline 設定，`nvinferserver` 對接 Triton、NvDCF tracker、RTSP sink、Kafka broker 都有配置 |
| [`inference_test.py`](inference_test.py) | `Fall/tools/` | 早期的邊緣推論主程式，含 GStreamer 硬體解碼拉流的實作 |
| [`rtdetr-l-deim.yaml`](rtdetr-l-deim.yaml) | `Fall/tools/` | DEIM 版 RT-DETR 骨幹設定 |
| [`CctvGridTile.tsx`](CctvGridTile.tsx) | `frontend/src/components/` | 九宮格電視牆的前端元件 |
| [`start_edge.sh`](start_edge.sh) / [`start_cloud.sh`](start_cloud.sh) | 專案根目錄 | 邊緣端與雲端的啟動腳本 |
| [`README_MLOps_SOP.md`](README_MLOps_SOP.md) | 專案根目錄 | 早期的 MLOps 操作手冊 |

---

## 各項為什麼沒有進入正式管線

### DeepStream

`nvinferserver` 外掛可以直接對接 Triton，由 GStreamer pipeline 統一處理解碼、
批次化與追蹤，在多路相機的場景下是最貼合本專案架構的方案。沒有採用的原因有四個：

1. 設定檔引用的 `config_infer_triton.txt` 不存在，本身是無法執行的骨架
2. `[message-broker0]` 直接送 `processed-reports`，訊息格式是 NVIDIA 自訂 schema，
   與後端的欄位定義不符，會違反本專案的契約規則（見 [`CLAUDE.md`](../../CLAUDE.md) 第一節）
3. `[primary-gie]` 只掛得了一顆模型，而本專案需要三顆，
   其中 Action Transformer 是吃 30 幀視窗的時序模型，跨幀狀態要另外用 probe callback 實作
4. DeepStream SDK 只支援 Linux 與 NVIDIA GPU，macOS 開發機無法運行

### GStreamer 拉流

`inference_test.py` 中的實作方式：

```python
gst_pipeline = (
    f"rtspsrc location={rtsp_url_ipv4} protocols=tcp latency=0 ! "
    f"rtph264depay ! h264parse ! decodebin ! videoconvert ! "
    f"video/x-raw, format=BGR ! appsink drop=true sync=false"
)
cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)
```

改用 PyAV 的兩個理由：OpenCV 需在編譯時啟用 GStreamer 支援（pip 安裝的官方 wheel 不含），
以及這條 pipeline 寫死 H.264，而測試素材含 AV1 編碼，解不開。
現行實作見 [`ai/av_reader.py`](../../ai/av_reader.py)，它的低延遲參數即是對齊這裡 `latency` 設定的意圖。

### DEIM 版 RT-DETR

`nc: 3`（person / bed / wheelchair）與本專案 `data.yaml` 的類別集合對不上，
且本專案的訓練是從 `rtdetr-l.pt` 繼承權重，用 yaml 從零建模型與滾動式重訓的設計衝突。

### 啟動腳本

`start_edge.sh` 與 `start_cloud.sh` 內含寫死的 `localhost` 與虛擬環境路徑，
與本專案的 docker compose 部署方式衝突。
其中 ffmpeg 的參數（`-nostdin`、`-tune zerolatency -g 30`）有參考價值。

---

## 修改紀錄

`inference_test.py` 第 56 行原本有一組硬編碼的 API 金鑰，
歸檔時已替換為 `***REDACTED***`。除此之外所有檔案均為原始內容，未做其他更動。

更完整的評估紀錄（包含哪些項目已經移植進 `main`、哪些是刻意不採用）
見 [`CHANGELOG-STAGES.md`](../CHANGELOG-STAGES.md)。

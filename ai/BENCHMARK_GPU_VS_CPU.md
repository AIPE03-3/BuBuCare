# Triton GPU vs CPU 同機效能對照

**2026-07-28 實測**。同一台機器、同一個 Triton 映像檔、同一批輸入畫面，只差
「模型跑在 GPU 還是 CPU」。目的是回答一個問題：**這套管線沒有 GPU 撐不撐得住。**

## 環境

| 項目 | 值 |
|---|---|
| CPU | AMD Ryzen 7 7800X3D（8 核 16 執行緒） |
| GPU | NVIDIA GeForce RTX 5060 Ti（Blackwell），driver 610.74 |
| Triton | `nvcr.io/nvidia/tritonserver:25.10-py3` |
| GPU 側 | 容器 `nh-triton`，HTTP 8010 / metrics 8002，`--gpus all` |
| CPU 側 | 容器 `nh-triton-cpu`，HTTP 8020 / metrics 8022，**不帶 `--gpus`**，CPU 全核不設限 |
| 輸入 | `ai/test_demo/test1.mp4` 前 30 幀，兩側餵完全同一批 |
| 量測腳本 | [`ai/bench_triton.py`](bench_triton.py)（單顆模型）、`ai/inference_test.py`（端到端） |
| 原始資料 | `ai/bench_results/*.json`（不進版控） |

**方法**：GPU 側 100 次（warmup 10），CPU 側 50 次（warmup 5），單執行緒序列送件。
兩台 Triton **不同時受測** —— CPU 版會吃滿所有核心，連帶拖慢 GPU 側 client 的前處理，
同時跑的話兩邊數字都不對。跑哪一邊就把另一邊 `docker stop`。

量兩層：
- **client 端** = 前處理 + 網路 + 推論 + 後處理，也就是主迴圈實際等待的時間
- **server compute** = 從 Triton 自己的 `/metrics` 前後差值算出的**純模型計算**時間

---

## 關鍵限制：CPU 側的 rt_detr 只能用 ONNX

GPU 上線用的 `rt_detr` 是 `platform: tensorrt_plan`，跑的是 Blackwell 專屬編出的
`model.plan`。**TensorRT 引擎不可能在 CPU 上執行**，換 `KIND_CPU` 也沒用。所以 CPU 側
改用同一顆模型的 ONNX 版本（`rt_detr_onnx`）。

因此對照必須拆成兩張表，否則數字不誠實：**表 A** 兩邊都用 ONNX，看的是純硬體差距；
**表 B** 用兩邊各自的上線配置，看的是實際決策數字。

---

## 表 A：同格式對照（ONNX vs ONNX）—— 純硬體差距

| 模型 | GPU mean | CPU mean | **倍數** | GPU p95 | CPU p95 | GPU server compute | CPU server compute |
|---|---:|---:|---:|---:|---:|---:|---:|
| `yolo_pose` | 22.52 ms | 76.10 ms | **3.4×** | 35.59 ms | 123.78 ms | 13.28 ms | 60.15 ms |
| `rt_detr_onnx` | 29.23 ms | 192.00 ms | **6.6×** | 48.59 ms | 285.48 ms | 20.96 ms | 176.40 ms |
| `action_transformer` | 2.08 ms | **0.78 ms** | **0.4×**（CPU 較快）| 3.44 ms | 0.88 ms | 1.58 ms | 0.20 ms |

## 表 B：上線配置對照（GPU=TensorRT plan vs CPU=ONNX）

| 模型 | GPU（上線用） | CPU（最佳可行） | **倍數** | GPU 吞吐 | CPU 吞吐 |
|---|---:|---:|---:|---:|---:|
| `yolo_pose`（ONNX 兩邊相同）| 23.82 ms | 76.10 ms | **3.2×** | 42.0 infer/s | 13.1 infer/s |
| `rt_detr` → TensorRT vs ONNX | 17.33 ms | 192.00 ms | **11.1×** | 57.7 infer/s | 5.2 infer/s |
| `action_transformer` | 2.18 ms | 0.78 ms | 0.4× | 458.8 infer/s | 1279.9 infer/s |

**順帶量到的 TensorRT 效益**：同樣在 GPU 上，`rt_detr` 用 TensorRT plan（17.33 ms）比用
ONNX（29.23 ms）快 **1.7 倍**，server compute 從 20.96 ms 降到 6.94 ms。這是編譯成
Blackwell 專屬引擎換來的，也是為什麼 `rt_detr` 值得維持 `tensorrt_plan` 的麻煩
（每個版本目錄都要配一份 `.plan`，見 [`triton_repo/README.md`](triton_repo/README.md) 的事故記錄）。

## 表 C：端到端 processed FPS

單路相機、`test4.mp4`（4.9 分鐘長片）、`NO_RENDER=1 FPS_NO_THROTTLE=1 DETR_EVERY_N=1`，
量的是「經過三顆模型推論的幀」的處理速率。

| 配置 | 穩態 FPS | 對 30 fps 門檻 |
|---|---:|---|
| GPU（rt_detr TensorRT）| **10.8 fps** | ✗ 未達 |
| CPU（rt_detr_onnx）| **3.2 fps** | ✗ 差很遠 |
| GPU + `DETR_EVERY_N=10`（上線建議組合）| **15.6 fps** ※ | ✗ 未達，但已過 30fps 來源的隔幀處理需求 |

※ 15.6 fps 取自 [`FPS_NOTES.md`](FPS_NOTES.md) 既有量測，本輪未重跑。
本輪 GPU 的 10.8 fps 與 FPS_NOTES 的基準 11.0 fps 一致（±0.5 fps 是噪音），可以對得上。

---

## 結論

1. **CPU 撐不住，差距不是調參能補的。** 端到端 10.8 → 3.2 fps，**3.4 倍**。
   即使套上 `DETR_EVERY_N=10` 這類降頻手段，CPU 側樂觀估也只到 5~6 fps，
   而且 pose 必須每幀跑（要餵連續 30 幀給 AcT，時序不能有洞），降不下去。
2. **瓶頸是 `rt_detr`，不是 pose。** CPU 上單次 192 ms，占端到端每幀時間的絕大部分；
   同一顆在 GPU 上用 TensorRT 只要 17 ms，差 **11 倍**。要在 CPU 上跑，第一件事是
   把 rt_detr 換掉或大幅降頻，不是去優化 pose。
3. **`action_transformer` 在 CPU 上反而比 GPU 快（0.78 ms vs 2.08 ms）。**
   這顆模型只有 315 KB，計算量小到 GPU 的 kernel 啟動與 PCIe 來回搬運成本
   比算它本身還貴。**如果之後要做混合部署，這顆放 CPU 是划算的**，可以把 GPU 空出來
   給 pose 和 detr。
4. **多路相機的推論**：GPU 單路 10.8 fps，三路併發就會互相稀釋；CPU 連單路都只有 3.2 fps，
   多路完全不用談。要上多路，優先做的是 dynamic batching 與多 instance
   —— 目前四顆 config 全是 `max_batch_size: 0` + `count: 1`，等於完全沒開這兩項。

## 怎麼重跑

```bash
# 1) 產生 CPU 版 model repository（config 改 KIND_CPU，權重用 hardlink）
./ai/make_cpu_repo.sh

# 2) GPU 側（Triton 已在 8010/8002）
cd ai && .venv/bin/python bench_triton.py --label gpu \
    --base http://127.0.0.1:8010 --metrics http://127.0.0.1:8002/metrics

# 3) 換 CPU 側（先停掉 GPU 那台，不要同時受測）
./ai/run_triton.sh stop
TRITON_NAME=nh-triton-cpu TRITON_GPUS=none \
HTTP_PORT=8020 GRPC_PORT=8021 METRICS_PORT=8022 \
MODEL_REPO="$(pwd)/ai/triton_repo_cpu" \
LOAD_MODELS="yolo_pose rt_detr_onnx action_transformer" ./ai/run_triton.sh

cd ai && .venv/bin/python bench_triton.py --label cpu \
    --base http://127.0.0.1:8020 --metrics http://127.0.0.1:8022/metrics \
    --detr-model rt_detr_onnx --iters 50 --warmup 5

# 4) 端到端 FPS（兩邊各跑一次，只換 TRITON_*_URL；CPU 側 detr 要指向 rt_detr_onnx）
SINGLE_SOURCE=ai/test_demo/test4.mp4 NO_RENDER=1 FPS_NO_THROTTLE=1 DETR_EVERY_N=1 \
TRITON_POSE_URL=http://127.0.0.1:8010/yolo_pose \
TRITON_DETR_URL=http://127.0.0.1:8010/rt_detr \
TRITON_ACT_URL=http://127.0.0.1:8010/action_transformer \
.venv/bin/python -u inference_test.py

# 5) 復原
TRITON_NAME=nh-triton-cpu ./ai/run_triton.sh stop
HTTP_PORT=8010 GRPC_PORT=8011 METRICS_PORT=8002 ./ai/run_triton.sh
```

## 數字的可信度邊界

- 依 [`CONTRIBUTING.md`](../CONTRIBUTING.md) 第四節與 `FPS_NOTES.md`：**只在同一台機器上比前後差異**，
  不要跨機器比較；端到端 FPS 的 ±0.5 fps 是噪音。
- 單顆模型的 client mean 在兩輪之間會有 ~5% 浮動（GPU clock 狀態、其他容器的干擾）。
  跨表比較時請用**同一輪**的數字：表 A 用 `gpu-onnx` 那一輪，表 B 的 rt_detr 用 `gpu` 那一輪。
- CPU 側沒有固定執行緒數（`TRITON_CPUS` 未設 = 全 16 執行緒可用）。要更嚴謹的可重現性，
  用 `TRITON_CPUS=0-7` 之類固定核心再跑一次。
- `action_transformer` 的輸入是固定 seed 產生的 (30,34) 特徵陣列，不是真實 pose 序列。
  Transformer 的計算量只跟形狀有關、與內容無關，兩側餵的完全相同，所以對照是成立的。

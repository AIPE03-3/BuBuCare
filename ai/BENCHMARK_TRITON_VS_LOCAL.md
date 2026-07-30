# Triton vs 不用 Triton：同機同卡效能對照

**2026-07-30 實測**。同一台機器、同一張 GPU、同一批輸入畫面、同一組權重，
只差**模型是架在 Triton 伺服器上，還是直接載進推論 process**。

目的是回答：**Triton 這一層（每幀一趟網路來回）讓我慢了多少，換來的好處值不值得。**

> **這份與 [`BENCHMARK_GPU_VS_CPU.md`](BENCHMARK_GPU_VS_CPU.md) 量的是不同的軸。**
> 那份是「Triton 跑 GPU vs Triton 跑 CPU」——兩邊都經過 Triton，答的是「沒 GPU 撐不撐得住」
> （結論：撐不住）。這份答的是「Triton 這層值不值得」。兩份不要混著讀。

## 環境

| 項目 | 值 |
|---|---|
| CPU | AMD Ryzen 7 7800X3D（8 核 16 執行緒） |
| GPU | NVIDIA GeForce RTX 5060 Ti（Blackwell），driver 610.74 |
| Triton | `nvcr.io/nvidia/tritonserver:25.10-py3`，容器 `nh-triton`，HTTP 8010 / gRPC 8011 / metrics 8002 |
| 本地側 | torch 2.13.0+cu130、ultralytics 8.4.96，權重直接載進 process |
| 量測腳本 | [`bench_triton.py --backend triton\|local`](bench_triton.py)（單顆）、[`inference_test.py`](inference_test.py) + `INFER_BACKEND`（端到端）|
| 前置驗證 | [`verify_backend_parity.py`](verify_backend_parity.py) |
| 原始資料 | `ai/bench_results/20260730_*_t8-*.json`（單顆）、`*_t4-*.json`（舊輪）；不進版控 |

### 用哪支影片，為什麼分兩支

| 影片 | 規格 | 用在 | 為什麼 |
|---|---|---|---|
| **`test8.mp4`** | H.264 1080p 15fps、**248 幀 / 16.5 秒** | **單顆模型** | 內容最合適：`rt_detr` v2 信心穩定在 **0.77–0.98**（每幀都真的偵測到），且人數由 **1 人漸增到 3 人**，pose 的後處理負載有真實的變化範圍。單顆只需前 30 幀，長度足夠。 |
| **`test4.mp4`** | H.264 1080p 24fps、**7086 幀 / 4.9 分鐘** | **端到端 FPS** | 端到端要跑到**穩態**才有意義。實測 `test8` 只跑到約 120 個處理幀就結束，本地側還在冷啟爬升（3.5 → 5.9 → 7.1 fps）、累計均 5.0 fps 純粹是冷啟假象。必須用長片。 |

單顆模型：取前 30 幀輪流餵、每輪 100 次（warmup 10）、單執行緒序列送件，兩側完全同一批。
端到端：跑整支影片，`NO_RENDER=1 FPS_NO_THROTTLE=1`。
**每組配置跑兩輪**，本文所有單顆模型數字都是兩輪平均，結論只建立在兩輪都可重現的方向上。

> **不要用 `test1.mp4` 跑這個對照**：`rt_detr` v2 在那支上**完全不觸發**（最高信心 0.123
> < conf 門檻 0.35，偵測 0 個框），Triton 側會因此幾乎不做後處理、對照不乾淨。
> 詳見文末「順帶抓到的問題」。

---

## 前置閘門：兩條路算出來的東西必須一樣

效能數字只有在「兩邊做的是同一件事」時才有意義。跑分之前先過
[`verify_backend_parity.py`](verify_backend_parity.py)：

| 比對項 | max 絕對誤差（`test8`）| 門檻 | |
|---|---:|---:|---|
| `yolo_pose` box（原圖 px）| 0.016 | 2.0 | ✅ |
| `yolo_pose` keypoint（原圖 px）| 0.034 | 2.0 | ✅ |
| `action_transformer` logits | 0.0021 | 0.01 | ✅ |

這個量級是 FP32 kernel 實作與運算順序造成的浮點噪音，**兩條路算的是同一個東西**。

### ⚠️ 這道閘門抓到一個會讓對照不公平的差異（已修）

第一次跑 parity 時 keypoint 差到 **65.9 px**，而 box 只差 2 px —— 同一個人、位置對得上，
但關鍵點全體位移。原因是**兩邊餵給模型的畫面解析度不同**：

- ultralytics 預設 `rect=True`：1920×1080 letterbox 成 **640×384**（保比例、最小填充）
- [`triton_pose_client.py:59`](triton_pose_client.py) 寫死 **640×640** 方形

不修的話本地側每幀少算 40% 的畫素，會**不公平地佔便宜**。本地 client 改
`rect=False` 對齊後降到 0.25 px（見 [`local_pose_client.py`](local_pose_client.py) 的註解）。
**這是本輪最容易搞錯的地方**：如果只看 FPS 不看 parity，會得到一個本地側虛高的結論。

---

## 表 A：單顆模型延遲（主表，兩邊同權重）

`yolo_pose` 與 `action_transformer` 兩邊是**同一顆權重**的不同格式
（`.pt` 走 PyTorch vs 同一顆匯出的 ONNX 走 Triton），單一變因＝有沒有 Triton。
數字皆為兩輪平均。

| 模型 | Triton HTTP | Triton gRPC | 本地 | 本地 vs Triton(gRPC) |
|---|---:|---:|---:|---|
| `yolo_pose` mean | 21.95 ms | 19.86 ms | **14.21 ms** | 本地快 **1.40×** |
| `yolo_pose` p95 | 29.34 ms | 34.13 ms | 32.88 ms | 互有高低（見下）|
| `yolo_pose` p99 | 32.94 ms | 42.29 ms | 35.82 ms | 互有高低 |
| `action_transformer` mean | 1.49 ms | 1.77 ms | **1.45 ms** | 本地快 **1.21×** |
| `action_transformer` p95 | 3.09 ms | 3.64 ms | 2.07 ms | 本地較短 |

**Triton 這層的成本可以直接拆出來**（client wall time − server 純計算）：

| 模型 | | client mean | server compute | server queue | **差額＝Triton 這層** |
|---|---|---:|---:|---:|---:|
| `yolo_pose` | gRPC | 19.86 ms | 12.55 ms | 0.05 ms | **7.32 ms** |
| | HTTP | 21.95 ms | 11.49 ms | 0.05 ms | **10.46 ms** |
| `rt_detr` | gRPC | 12.90 ms | 7.20 ms | 0.06 ms | **5.70 ms** |
| | HTTP | 15.40 ms | 6.35 ms | 0.06 ms | **9.05 ms** |
| `action_transformer` | gRPC | 1.77 ms | 1.25 ms | 0.04 ms | **0.52 ms** |
| | HTTP | 1.49 ms | 1.02 ms | 0.04 ms | **0.47 ms** |

**gRPC 比 HTTP 省掉約 3 ms/次**（pose 10.46→7.32、detr 9.05→5.70），與
[`FPS_NOTES.md`](FPS_NOTES.md) 記的 +4% 端到端增益方向一致。
`queue` 三顆都 ~0.05 ms，確認單執行緒送件沒有排隊，`count: 1` 單 instance 不是瓶頸。

> 這個「差額」不是純網路時間，它包含序列化／反序列化與 client 端前後處理的實作差異
> （Triton 版的 pose 後處理是手寫 NMS，本地是 ultralytics 內部做掉）。見文末可信度邊界。

**關於 p95/p99：`yolo_pose` 的尾延遲三種配置互有高低**（HTTP 29.3 / gRPC 34.1 / 本地 32.9），
兩輪之間也不穩定。**這一欄不足以支持任何結論** —— 尾巴受 GPU clock 狀態與其他容器干擾
的程度比 mean 大得多，要真的比尾延遲得跑更多輪、或固定 GPU 頻率。
`action_transformer` 的尾巴則是本地明確較短（2.07 vs 3.64），與 mean 同向、可信。

## 表 B：`rt_detr`（附表，兩邊不是同一顆模型）

| | Triton 的 `rt_detr` | 本地 |
|---|---|---|
| 權重 | v2 重訓版，**5 類**（person/chair/sofa/bed/tv）| `rtdetr-l.pt`，**COCO 80 類** |
| 格式 | **TensorRT plan**（Blackwell 專屬編譯）| PyTorch |

| | Triton HTTP | Triton gRPC | 本地 | |
|---|---:|---:|---:|---|
| mean | 15.40 ms | **12.90 ms** | 31.64 ms | Triton(gRPC) 快 **2.45×** |
| p95 | 18.66 ms | 18.71 ms | 55.10 ms | Triton 尾巴短得多 |
| p99 | 20.68 ms | 20.06 ms | 61.79 ms | Triton 尾巴短得多 |

**這顆是唯一 Triton 明顯勝出的模型，但倍數不能歸給「Triton 這層」** —— 混了格式
（TensorRT vs PyTorch）與類別數兩個變因。既有文件已量過同在 GPU 上 TensorRT 比 ONNX
快 1.7×，所以這裡的優勢主要是**編譯成 TensorRT 引擎**換來的，那正是 Triton 讓這件事變得
可行的原因。

**還有第三個變因對 Triton 有利**：本地 COCO 80 類在 `test8` 上偵測到 **11–14 個框**，
而 Triton 的 v2 只有 5 類、偵測 **1–4 個框**（`verify_backend_parity.py` 印得出來）。
框越多後處理越重，所以本地側在這顆吃了額外的虧。真要單一變因，得把 v2 的 `.pt`
撈出來當本地權重（`model_deployment_agent.py` 從 ClearML 拉的那份），屬於下一輪。

## 表 C：端到端 processed FPS（最有決策價值的數字）

單路、**`test4.mp4` 整支**（長片才到穩態，見上面「用哪支影片」）、
`NO_RENDER=1 FPS_NO_THROTTLE=1`，量「經過三顆模型＋六大防線的幀」的處理速率。

| 配置 | Triton（HTTP）| 本地 | 贏家 |
|---|---:|---:|---|
| `DETR_EVERY_N=1`（detr 每幀跑）| **9.4–9.6 fps** | 8.1–8.3 fps | **Triton 快 ~15%** |
| `DETR_EVERY_N=10` + `DECODE_PREFETCH=1`（**上線建議組合**）| 12.4–12.5 fps | **13.4 fps** | **本地快 ~7%** |

### ⭐ 結論會因配置而反轉 —— 這是本輪最重要的發現

- **detr 每幀都跑時，Triton 勝**：`rt_detr` 是最重的一顆，它的 TensorRT 優勢（快 2.45×）
  足以蓋過三顆模型加起來的 serving overhead。
- **detr 降頻到 1/10 後，本地勝**：Triton 的強項（detr）只剩十分之一的份量，
  而本地的強項（pose 快 1.40×、act 快 1.21×）**每幀都在生效**。

反轉那組跑了兩次都重現（Triton 12.4 / 12.5，本地 13.4 / 13.4）。

**所以「Triton 值不值得」沒有單一答案，取決於 `DETR_EVERY_N`。**
而上線建議組合正是 `DETR_EVERY_N=10` 那一組。

（對照 [`FPS_NOTES.md`](FPS_NOTES.md) 既有基準：本輪 Triton 側短片量到 10.8 fps、
長片 9.4–9.6 fps，與該檔記的 ~11.0 fps 基準在同一量級。長片略低是因為整支影片的人數與
場景複雜度比前 30 幀高，屬正常；`DETR_EVERY_N=10` 那組 12.5 fps 對比該檔的 15.6 fps 偏低，
差在本輪端到端沒開 gRPC。跨檔比較請只看方向、不要直接相減。）

## 表 D：Triton 的非速度優勢（只量穩態延遲會漏掉）

| 項目 | Triton | 本地 | 說明 |
|---|---:|---:|---|
| 冷啟（建 client + 首次三顆推論）| **2.7–3.1 s** | 4.5 s | 本地要現場把 `.pt` 讀進顯存；Triton 容器啟動時就載好了 |
| 推論 process 的 GPU 顯存增量 | **−3 ~ +20 MB**（≈0）| **+448 ~ +496 MB** | 權重不在 client 端 |

**冷啟這一項在短影片上不只是啟動延遲，它會吃掉整個量測。** 端到端跑 `test8`（248 幀）時
本地側從 3.5 fps 爬到 7.1 fps 都還沒到穩態，累計均 5.0 fps 是假象 ——
這就是為什麼端到端一定要用長片。

**顯存那一欄是多路部署的關鍵。** 本地模式下每條 `camera_worker` 執行緒各載一份權重
（thread-local，見 [`local_pose_client.py`](local_pose_client.py) 的註解），
**三路就是約 1.5 GB**；Triton 是一份權重供所有相機共用，多幾路都一樣。

此外 Triton 才有的能力（本輪沒量，但是決策的一部分）：
- **模型熱抽換與回滾** —— [`model_deployment_agent.py`](model_deployment_agent.py) 換版／
  `--rollback` 完全靠 Triton 的 version_policy，本地模式沒有這條路
- **多 client 共用** —— `inference_to_labelstudio_sdk.py` 也打同一顆線上 `rt_detr`，
  驗的就是上線那份

---

## 順帶抓到的問題：`rt_detr` v2 在 `test1.mp4` 上完全不觸發

一致性驗證印出「Triton 側 15 幀全部 0 個框，本地側 4–5 個框」，追下去發現
**v2 模型在 `test1.mp4` 上 300 個 query 的最高信心只有 0.123**，遠低於 `conf=0.35` 門檻，
所以全被濾掉。

但這**不是模型壞了**，換影片就正常：

| 影片 | v2 最高信心 | `conf>0.35` 的框數 |
|---|---:|---:|
| `test1.mp4` | 0.123 | **0** |
| `test4.mp4` | 0.985 | 5 |
| `test6.mp4` | 0.900 | 2 |

| `test8.mp4` | 0.77–0.98（每幀）| 1–4 |

是 `test1.mp4` 這支的場景與 v2 的訓練集不合（v2 是 2026-07-29 重訓的 5 類版，
mAP50=0.9912 是在自家資料集上）。**這是 D 組訓練資料涵蓋度的線索，值得回報**：
v2 對某些場景的泛化不足，而不是量測問題。

**對本輪的處理**：這是換影片的起因。`test1.mp4` 那組數字（Triton detr 因 0 個框而少做
後處理，對 Triton 有利）已作廢不列入本文。單顆模型改用 `test8.mp4` 後 detr 倍數量到
**2.45×**（中途用 `test4.mp4` 量到 2.16×），三支影片**方向完全一致**，結論不受影片選擇影響。

---

## 結論

1. **Triton 這層的成本是每次 5.7–7.3 ms（gRPC）或 9.1–10.5 ms（HTTP）。** 這是拿 client
   wall time 減掉 Triton 自報的純計算時間直接量到的（`action_transformer` 例外，
   只有 0.5 ms，因為它的張量小到序列化成本可忽略）。
2. **要不要用 Triton 取決於 `DETR_EVERY_N`，沒有單一答案。**
   每幀跑 detr → Triton 快 15%；降頻到 1/10（上線建議組合）→ 本地快 7%。
   **兩個差距都不大**，這代表速度不該是這個決策的主要依據。
3. **速度差距小，而 Triton 的架構優勢是本地給不了的**：熱抽換／回滾、多路共用一份權重
   （本地三路要多吃 ~1.5 GB 顯存）、多 client 共用同一份上線模型。
   **綜合建議：維持 Triton**，並把端到端也改用 gRPC（省 ~3 ms/次、零程式碼改動，
   只改 URL scheme）。
4. **本地模式的價值在診斷，不在生產。** 它是一把量尺：
   之後懷疑「是 serving 慢還是模型慢」時，切 `INFER_BACKEND=local` 就能分離變因。
   本輪就是這樣拆出「pose 的 12.55 ms 是模型算的、7.32 ms 是 serving 的」。
5. **`action_transformer` 走 Triton 的效益最薄**（本地快 1.21×，這層成本 0.52 ms 佔了
   它 gRPC 總延遲的 29%）。這與 `BENCHMARK_GPU_VS_CPU.md` 的第 3 點結論一致（這顆只有
   315 KB，搬運成本比計算本身還貴）。但它只佔端到端每幀約 1.8 ms，
   **把它從 Triton 拿下來的收益有限，還會失去熱抽換，優先度低。**

## 怎麼重跑

```bash
# 0) 前置閘門：兩條路算出來的東西必須一樣（不過這關，下面的數字都不可信）
cd ai && .venv/bin/python verify_backend_parity.py

# 1) 單顆模型三組，用 test8（各跑兩輪，本文數字是兩輪平均）
#    --video 預設就是 test8.mp4，下面寫出來只是為了明確
cd ai && .venv/bin/python bench_triton.py --label t8-triton-http --backend triton \
    --base http://127.0.0.1:8010 --metrics http://127.0.0.1:8002/metrics \
    --video test_demo/test8.mp4
cd ai && .venv/bin/python bench_triton.py --label t8-triton-grpc --backend triton \
    --base grpc://127.0.0.1:8011 --metrics http://127.0.0.1:8002/metrics \
    --video test_demo/test8.mp4
cd ai && .venv/bin/python bench_triton.py --label t8-local --backend local \
    --video test_demo/test8.mp4

# 2) 端到端用 test4（長片才到穩態，不要用 test8）
#    從 repo 根目錄跑；SINGLE_SOURCE 是相對根目錄的路徑。只換 INFER_BACKEND。
SINGLE_SOURCE=ai/test_demo/test4.mp4 NO_RENDER=1 FPS_NO_THROTTLE=1 DETR_EVERY_N=1 \
HEADLESS=1 FPS_LOG_EVERY=60 INFER_BACKEND=triton ai/.venv/bin/python -u ai/inference_test.py
# 同一行換 INFER_BACKEND=local 再跑一次

# 3) 上線建議組合（結論會反轉的那組）
#    上面兩行各加 DETR_EVERY_N=10 DECODE_PREFETCH=1
```

`INFER_BACKEND` 未設＝`triton`＝與改動前行為完全相同。生產一律不要設它。

## 數字的可信度邊界

- 依 [`CONTRIBUTING.md`](../CONTRIBUTING.md) 第四節與 [`FPS_NOTES.md`](FPS_NOTES.md)：
  **只在同一台機器比前後差異**，不要跨機器比。端到端 FPS ±0.5 fps 是噪音。
- **單顆模型 mean 兩輪之間有 5–15% 浮動**（例：`yolo_pose` Triton HTTP 兩輪 20.90 / 23.00 ms、
  `action_transformer` 本地 1.92 / 0.98 ms）。本文所有單顆數字都是**兩輪平均**，
  且結論只建立在兩輪都可重現的方向上，不要拿單一輪的絕對值去算精確倍數。
  **`action_transformer` 的 1.21× 是本文最不穩的一個倍數**（該顆只有 1–2 ms，
  浮動幅度與差距同量級），只當「本地略快」看，不要引用這個數字。
- **p95/p99 只有 `rt_detr` 那組可信**（Triton 18.7 vs 本地 55.1，差距遠大於噪音）。
  `yolo_pose` 的尾延遲三種配置互有高低且兩輪不穩，不足以支持結論。
- **表 A 的「差額」不是純網路時間。** 它還包含序列化成本，以及兩側 client 端前後處理的
  實作差異——Triton 版的 pose 後處理是手寫 NMS + letterbox 反算
  （[`triton_pose_client.py`](triton_pose_client.py) 只拿得到 raw tensor），
  本地版是 ultralytics 內部做掉。所以「Triton 這層」嚴格說是
  「serving 往返 + 手寫後處理相對官方實作的差異」。要再切細，得在兩側各自埋前後處理計時。
- **影片會影響什麼、不影響什麼**（本輪跨 test1／test4／test8 三支驗過）：
  · `action_transformer` **完全不受影響**（輸入是固定 seed 的合成陣列，沒吃影片）；
  · `rt_detr` **幾乎不受**（固定 300 queries，算量與畫面內容無關——Triton 側實測
    test1 14.78 / test4 15.02 / test8 15.40 ms，全在 4% 內）；
  · `yolo_pose` **會受**（人越多，NMS 與座標反算越重），但兩側餵完全同一批幀，
    所以**倍數**穩定（test4 量到 1.62×、test8 量到 1.40×，同向）；
  · 端到端 FPS 的**絕對值**受影響明顯，但**「結論會反轉」是結構性的**
    （detr 降頻後 Triton 的強項失去份量），不隨影片改變。
  · **真正會被影片毀掉的是「模型有沒有觸發」**：`test1.mp4` 上 rt_detr v2 零偵測，
    那組數字必須作廢。**選 benchmark 影片時先確認兩側都真的偵測到。**
- **影片長度決定端到端數字能不能用**：`test8`（248 幀）本地側還在冷啟爬升就結束了，
  累計均 5.0 fps 是假象。端到端**一定要用長片**（`test4` 7086 幀），單顆模型才可以用短片。
- 本輪**只比 GPU**。CPU 側見 [`BENCHMARK_GPU_VS_CPU.md`](BENCHMARK_GPU_VS_CPU.md)。
- 本輪**只量單路**。多路併發沒量，而那是 Triton 最有利的情境（共用權重、可開 dynamic
  batching）。目前四顆 config 全是 `max_batch_size: 0` + `count: 1`，兩項都沒開。
  **要做多路部署的決策，這份數據不夠，得先補多路量測。**

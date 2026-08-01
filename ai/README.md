# `ai/` — 邊緣推論層

攝影機畫面進來 → 三顆模型判斷有沒有人跌倒 → 事件發進 Kafka。
模型的重訓迴路（標註 → 訓練 → 熱部署）也在這一層。

**這份只是 `ai/` 的檔案索引。** 要理解整個系統怎麼運作、資料怎麼流，看
[`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)；動工前的硬規則在
[`../CLAUDE.md`](../CLAUDE.md)。

---

## ⚠️ 三個最容易踩的雷

1. **Triton 的 HTTP 埠是 8010 不是 8000。** 8000 被 backend 佔了。
   沒設 `TRITON_*_URL` 的話推論會打到 FastAPI 拿 404 然後**靜默降級**——
   畫面照跑、FPS 照印、零紅字，但姿態偵測全程失效。
   （`run_triton.sh` 的預設值寫的是 8000，起容器時要自己帶 `HTTP_PORT=8010`。）

2. **設定讀的是 repo 根目錄的 `.env`，不是 `ai/.env`。**
   走 [`backend_devices.py`](backend_devices.py) 的 `cfg()`。
   `ai/.env` 只有 ClearML 那支腳本在讀，放那裡的設定 `inference_test.py` 看不到。

3. **模型權重多數不進版控**（`.gitignore` 排除）。clone 下來要自己重建：
   `python ai/export_models.py --plan`。進版控的只有 `config.pbtxt`
   與 `yolo11s*.pt` / `action_transformer.pth`。

---

## 先讀哪一份

| 你想知道 | 看這份 |
|---|---|
| 跑多快、瓶頸在哪、怎麼提速 | [`FPS_NOTES.md`](FPS_NOTES.md) |
| 沒有顯示卡撐不撐得住 | [`BENCHMARK_GPU_VS_CPU.md`](BENCHMARK_GPU_VS_CPU.md)（結論：撐不住）|
| Triton 這層 serving 值不值得 | [`BENCHMARK_TRITON_VS_LOCAL.md`](BENCHMARK_TRITON_VS_LOCAL.md) |
| 重訓迴路怎麼跑 | [`MLOPS.md`](MLOPS.md) |
| Triton 上哪個模型是哪個版本 | [`triton_repo/README.md`](triton_repo/README.md) |

---

## 檔案地圖

### 主線：即時推論

| 檔案 | 做什麼 |
|---|---|
| ⭐ [`inference_test.py`](inference_test.py) | **主程式**。每支相機一條執行緒：拉流 → 三顆模型 → 六大防線 → 事件發 Kafka |
| [`triton_pose_client.py`](triton_pose_client.py) | 抓人體骨架（`yolo_pose`）|
| [`triton_detr_client.py`](triton_detr_client.py) | 認家具（`rt_detr`）|
| [`triton_act_client.py`](triton_act_client.py) | 判斷跌倒（`action_transformer`，吃連續 30 幀骨架）|
| [`av_reader.py`](av_reader.py) | 影片/RTSP 解碼。用 PyAV 而非 OpenCV，因為 test_demo 有 AV1 影片 |
| [`backend_devices.py`](backend_devices.py) | 跟後端要攝影機清單；`cfg()` 也是全 `ai/` 讀設定的入口 |
| [`detection_broadcaster.py`](detection_broadcaster.py) | 把骨架座標送給後端，前端 canvas 疊圖用（`DETECT_BROADCAST=1`）|
| [`modules/`](modules/) | 偵測模組。**白名單制，模組不准自己送 Kafka** —— 見 [`../CLAUDE.md`](../CLAUDE.md) 第一節 |

### 二審：低信心事件交給 VLM

| 檔案 | 做什麼 |
|---|---|
| [`vlm_worker.py`](vlm_worker.py) | 消費慢速道 Kafka，找 VLM 複判後回寫 |
| [`uncertainty_router.py`](uncertainty_router.py) | 決定「何時找 VLM、帶什麼 prompt、灰區怎麼分流」|
| [`vlm_client.py`](vlm_client.py) | VLM 呼叫介面，換後端（Ollama/雲端）不動呼叫端 |

> LangGraph 版的二審在 [`../agent/`](../agent/)，**目前是 shadow 模式**，
> 正式服務的仍是這裡的 `vlm_worker.py`。

### MLOps：標註 → 重訓 → 熱部署

| 檔案 | 做什麼 |
|---|---|
| [`inference_to_labelstudio_sdk.py`](inference_to_labelstudio_sdk.py) | 物件框的預標註推 Label Studio、人工標註拉回來 |
| [`pose_to_labelstudio_sdk.py`](pose_to_labelstudio_sdk.py) | 骨架版的同一件事 |
| [`labelstudio_client.py`](labelstudio_client.py) | 上面兩支共用的 Label Studio 連線管線 |
| [`prepare_dataset.py`](prepare_dataset.py) | 把標註清洗成可訓練的資料集（`--task pose` 走骨架線）|
| [`clearml_train_pipeline.py`](clearml_train_pipeline.py) | RT-DETR 滾動式重訓 |
| [`clearml_pose_train_pipeline.py`](clearml_pose_train_pipeline.py) | YOLO-Pose 滾動式重訓 |
| [`submit_task.py`](submit_task.py) | 把重訓任務排進 ClearML 佇列 |
| [`model_deployment_agent.py`](model_deployment_agent.py) | **熱部署**：拉 best 權重 → 轉檔 → 換 Triton 版本（`--rollback` 可回滾）|
| [`webhook_receiver.py`](webhook_receiver.py) | 接 Label Studio 的 webhook，標註量到門檻自動排重訓 |
| [`mlops_paths.py`](mlops_paths.py) | 上面這些腳本共用的路徑解析 |

### 工具與量測

| 檔案 | 做什麼 |
|---|---|
| [`run_triton.sh`](run_triton.sh) | 起 Triton 容器（⚠ 記得帶 `HTTP_PORT=8010`）|
| [`export_models.py`](export_models.py) | 把權重匯出成 Triton 吃得下的格式（`--plan` 編 TensorRT）|
| [`bench_triton.py`](bench_triton.py) | 單顆模型效能量測（`--backend triton\|local`）|
| [`verify_backend_parity.py`](verify_backend_parity.py) | 驗證 Triton 側與本地側算出來的東西一樣 |
| [`local_*_client.py`](local_pose_client.py) | 不走 Triton 的三支 client。**效能對照用，非生產路徑** |
| [`monitor_kafka.py`](monitor_kafka.py) | 看 Kafka 上實際流過什麼訊息 |
| [`watchdog.py`](watchdog.py) | 顧著推論行程，掛了自動重啟 |
| [`make_cpu_repo.sh`](make_cpu_repo.sh) | 產 CPU 版的 Triton model repository（GPU vs CPU 對照用）|

---

## 怎麼跑起來

**前置**：Triton 容器要起來、模型權重要在、根目錄 `.env` 要填好。

```bash
# 1) 起 Triton（三顆模型）—— 注意 HTTP_PORT
HTTP_PORT=8010 GRPC_PORT=8011 METRICS_PORT=8002 ./ai/run_triton.sh

# 2) 確認三顆都 ready（回 200 才算）
for m in yolo_pose rt_detr action_transformer; do
  curl -s -o /dev/null -w "$m %{http_code}\n" http://127.0.0.1:8010/v2/models/$m/ready
done

# 3) 跑推論（從 repo 根目錄跑，SINGLE_SOURCE 是相對根目錄的路徑）
python ai/inference_test.py
```

**壓測 / 量 FPS 時常用的開關**（未設＝原行為，都不影響推論邏輯）：

| 環境變數 | 作用 |
|---|---|
| `SINGLE_SOURCE=<檔案\|rtsp>` | 只掛一路，避免多路互相稀釋 |
| `NO_RENDER=1` | 跳過畫框渲染（HEADLESS 壓測用）|
| `FPS_NO_THROTTLE=1` | 不貼齊來源 fps，量純吞吐上限 |
| `DETR_EVERY_N=N` | 家具偵測每 N 幀跑一次（上線建議 10）|
| `DECODE_PREFETCH=1` | 解碼與推論重疊 |
| `INFER_BACKEND=local` | 不走 Triton（**效能對照用，非生產**）|

完整開關表與實測數字見 [`FPS_NOTES.md`](FPS_NOTES.md)。

**MLOps 那條迴路**要另外起 Label Studio 與 ClearML，日常開發不需要，見 [`MLOPS.md`](MLOPS.md)。

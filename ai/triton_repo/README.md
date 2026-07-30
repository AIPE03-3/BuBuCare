# Triton Model Repository — 版本管理

這個目錄是 Triton Inference Server 的 `--model-repository`。三顆模型：`yolo_pose`（人體姿態）、
`rt_detr`（環境物件偵測）、`action_transformer`（時序跌倒分類）。啟動見 [`../run_triton.sh`](../run_triton.sh)。

## 目前 serving 的版本（single source of truth）

| 模型 | serving 版本 | platform | 需要的權重檔（每個 serving 版本目錄都要有）| 版本鎖 |
|---|---|---|---|---|
| `yolo_pose` | 1 | onnxruntime_onnx | `1/model.onnx` | 無（只有 v1）|
| `rt_detr` | **2** | tensorrt_plan | `2/model.plan`（Blackwell 專屬 TensorRT 引擎）| ✅ `version_policy: specific [2]` |
| `action_transformer` | 1 | onnxruntime_onnx | `1/model.onnx` | 無（只有 v1）|

> 權重檔（`*.onnx` / `*.plan`）被 `.gitignore` 排除、**不進版控**，clone 後需在本機各自重建/取得：
> `python ai/export_models.py --plan`（三顆都重建到 v1）。進版控的只有 `config.pbtxt`。

## `rt_detr` 的版本沿革

| 版本 | 來源 | 類別 | 備註 |
|---|---|---|---|
| v1 | `rtdetr-l.pt` 官方權重 | COCO 80 類 | 原始上線版本，**保留當回滾點，不要刪** |
| **v2** | 2026-07-29 重訓（ClearML task `8d3d9421`）| person/chair/sofa/bed/tv 5 類 | mAP50=0.9912（見 [`../MLOPS.md`](../MLOPS.md) 對這個數字的但書）|

v2 是由 [`../model_deployment_agent.py`](../model_deployment_agent.py) 熱部署上去的，
`config.pbtxt` 的 `version_policy` 那一行由它自動改寫，**不要手動編輯**：

```bash
python ai/model_deployment_agent.py              # 部署 ClearML 上標 best 的最新權重
python ai/model_deployment_agent.py --rollback   # 切回上一個版本
```

換版本時 `rt_detr` 的類別語意會整個改變（v1 是 COCO 80 類、v2 是 5 類）。
這不影響跌倒偵測 —— `ai/inference_test.py:714-728` 算出來的 `detected_objects` /
`bed_box_xyxy` 全檔沒有任何地方讀（原本的讀取者 `bed_exit` / `chair_slip` 已於
2026-07-27 刪除）。**之後若要把那兩個值接回使用，先確認目前 serving 的是哪一版、
類別對照表拿的是哪一份**，否則會查到完全不相干的物件名。

## ⚠️ 版本鐵則（避免「載到沒測過/對不齊的版本」）

Triton 沒設 `version_policy` 時，**預設載「版本號最大」的版本目錄**。這會導致：只要有人往模型
目錄丟一個編號更大的版本，Triton 下次重啟就自動改載那個新版本——即使它還沒驗過、甚至缺權重檔。

**規則：**
1. 對 `platform: tensorrt_plan` 的模型（本專案的 `rt_detr`），每個「會被 serve 的版本目錄」
   都**必須有 Blackwell 編出的 `model.plan`**，光丟 `model.onnx` 沒用（onnx 不是 plan）。
2. 上新版本前，先在**該版本目錄**產出並驗證權重檔，驗過後才把 `config.pbtxt` 的
   `version_policy` 指到新版本號；不要靠「反正 Triton 會撿最大號」隱式切版。
3. 想維持「永遠只 serve 最新一個」可用 `version_policy: { latest { num_versions: 1 } }`，
   但仍要先確保最新版本目錄有合法權重檔，否則一樣會啟動失敗。

## 事故記錄

- **2026-07-26 — `rt_detr` 因 v3 缺 `model.plan` 導致 Triton 整支起不來。**
  現象：`rt_detr/3/` 只有 `model.onnx`、沒有 `.plan`，而能用的 Blackwell 引擎在 `rt_detr/1/model.plan`。
  Triton 預設載最大版本(3) → `unable to load plan file: /models/rt_detr/3/model.plan` →
  explicit 模式下這顆失敗使整個 server exit，連 `yolo_pose`/`action_transformer`（兩顆本來 READY）
  也一起無法服務。
  修法：在 [`rt_detr/config.pbtxt`](rt_detr/config.pbtxt) 加
  `version_policy: { specific { versions: [ 1 ] } }`，明確只 serve 有 `.plan` 的 v1。
  未來若要啟用 v3，先為 `rt_detr/3/` 補上 Blackwell `model.plan`、驗證通過，再改 `versions:`。

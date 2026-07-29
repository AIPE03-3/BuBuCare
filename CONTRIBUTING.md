# 協作須知（兩台機器：Linux + RTX 5060 Ti / macOS）

本專案同時在兩台機器上開發，最後 demo 以 **Linux + RTX 5060 Ti 那台**跑的結果為準。
兩邊環境差很多（CUDA vs MPS、`/home/` vs `/Users/`），以下是踩過雷之後定下來的規矩。

---

## 一、剛 clone / pull 下來要做的兩件事

### 1. 開啟本機護欄（每台機器做一次，永久生效）

```bash
git config core.hooksPath .githooks
```

git hooks **不會跟著 clone/pull 傳過來**，所以每台機器要自己開一次。
開了之後 `git commit` 當下就會擋掉常見錯誤，不用等 push 完才發現。

沒開也不會怎樣——GitHub Actions 那層一樣擋得住，只是回饋比較慢（要等 push）。

### 2. 重建模型檔（repo 裡沒有）

```bash
python ai/export_models.py --plan
```

`.onnx`（約 165MB）、`.plan`、`.pt`、長片 `test4.mp4`（344MB）都**不進 repo**
（GitHub 單檔上限 100MB）。`ai/triton_repo/` 裡只有 `config.pbtxt`，模型本體要自己在本機產。

[`ai/export_models.py`](ai/export_models.py) 從 `ai/` 底下的來源權重重建三顆：

| Triton 模型 | 來源權重 | 產出 |
|---|---|---|
| `yolo_pose` | `yolo11s-pose.pt` | `triton_repo/yolo_pose/1/model.onnx` |
| `rt_detr` | `rtdetr-l.pt`（首次執行 ultralytics 會自動下載）| `.../rt_detr/1/model.onnx` **＋ `model.plan`** |
| `action_transformer` | `action_transformer.pth`（要跟組員拿）| `.../action_transformer/1/model.onnx` |

⚠️ **`--plan` 不是選配**：這台的 `rt_detr` 是 `platform: tensorrt_plan`，只有 `model.onnx`
**Triton 會整支起不來**（explicit 模式一顆載入失敗會把另外兩顆一起拖垮，事故記錄見
[`ai/triton_repo/README.md`](ai/triton_repo/README.md)）。`--plan` 會另開一個 Triton 官方鏡像的
容器跑 `trtexec` 編出這台 GPU 專屬的引擎，**要 4 分鐘左右**，慢是正常的。

TensorRT 引擎綁「GPU 架構 + TensorRT 版本」，**不能跨機器複製**，每台要自己編。
Mac 沒有 NVIDIA GPU 編不出來，走第四節的兩個選擇。

匯出參數（固定/動態 shape、opset）是照著已進版控的 `config.pbtxt` 反推的，不是上游預設值，
**不要隨手改**——對不上 Triton 會直接拒載。

`ai/test_demo/` 只有 test1~3.mp4（各約 1.5MB）；test4.mp4 是 FPS 量測長片，要用請另外跟人要。

### 3. MLOps 迴路（標註 → 重訓 → 熱部署）

那條迴路的服務、腳本與跑法另外寫在 [`ai/MLOPS.md`](ai/MLOPS.md)，日常開發不需要起那些服務。

---

## 二、護欄擋什麼（`scripts/check_guardrails.py`）

| 擋 | 為什麼 |
|---|---|
| 家目錄絕對路徑 `/home/xxx/`、`/Users/xxx/` | 換一台機器就失效，這是兩邊互相弄壞對方最常見的原因 |
| 單檔 > 10MB | 模型/影片/資料集塞進 repo，push 不上去還要改寫歷史 |
| 明文密碼、AWS 金鑰 | 進了 git 就很難清乾淨 |
| `route_by_confidence()` 的 payload 欄位 | 後端 consumer 靠這組欄位寫 PostgreSQL，少一個就 422 退件 |

兩層執行：

- **本機 pre-commit**：commit 當下擋，回饋快。可以用 `--no-verify` 略過。
- **GitHub Actions**：push / PR 時擋，**不能略過，紅燈就是不能合**。

要放行特例：該行尾端加 `# guardrail: allow`，或在 `scripts/guardrails_allow.txt` 加整檔豁免
（加之前先想清楚是「規則不適用」還是「這次先過」——後者不該豁免）。

自己先跑一遍：

```bash
python3 scripts/check_guardrails.py
```

---

## 三、路徑怎麼寫才不會炸

**不要這樣：**

```python
env_path = '/home/rapubuntu/aipe03-3/ai/.env'      # 在 Mac 上必炸
data = '/Users/albert/aipe03-3/ai/data.yaml'        # 在 Linux 上必炸
```

**要這樣**（照 `ai/inference_test.py` 的做法）：

```python
import os
_AI_DIR = os.path.dirname(os.path.abspath(__file__))
data = os.path.join(_AI_DIR, "data.yaml")
```

**或給預設值的環境變數**（機器之間會變的東西都用這招）：

```python
TRITON_POSE_URL = os.environ.get("TRITON_POSE_URL", "http://127.0.0.1:8000/yolo_pose")
```

---

## 四、macOS 上怎麼跑

`ai/inference_test.py` 本身支援 Mac（`device` 會自動選 MPS），但**三顆模型都打 Triton**，
所以要有一個 Triton server 才跑得動。Mac 沒有 NVIDIA GPU，`ai/run_triton.sh` 的
`--gpus all` 用不了。兩個選擇：

1. **Mac 上跑 CPU 版 Triton**：把 `run_triton.sh` 的 `--gpus all` 拿掉自己起一份。慢，但邏輯測得動。
2. **連到 5060 Ti 那台**（同網段/tailscale）：

   ```bash
   export TRITON_POSE_URL=grpc://<那台的IP>:8011/yolo_pose
   export TRITON_DETR_URL=grpc://<那台的IP>:8011/rt_detr
   export TRITON_ACT_URL=grpc://<那台的IP>:8011/action_transformer
   ```

FPS 數字不要跨機器比較，只在同一台上比前後差異。

---

## 五、分支流程

demo 以 5060 Ti 那台為準，所以：

- **不要直接 push 到 `test/main-integration`**
- 開自己的分支 → 發 PR → 在 5060 Ti 上驗過 → 才合

PR 上 GitHub Actions 是綠燈才代表「沒踩到已知的雷」，不代表功能對；功能還是要在
5060 Ti 上實跑過。

---

## 六、不能動的東西

- **Kafka topic 名稱**：`processed-reports`、`nursing-home-alerts`
- **`route_by_confidence()` 的 payload 欄位**（護欄會擋）

這兩個是跟後端組講好的契約邊界。要改必須兩邊同時改，不是「我這邊跑得動」就算數。

- **`ai/modules/` 白名單**：只准存在、也只准 import `__init__.py` 與 `sanity_check.py`
  兩個檔（護欄會擋）。原本的 bed_exit / wandering / micro_motion / audio_fusion /
  chair_slip 五個模組已於 2026-07-27 刪除，功能與邏輯一律不再套用。
  理由與復活流程見 [`CLAUDE.md`](CLAUDE.md)。跌倒主邏輯在 `ai/inference_test.py`
  主迴圈，不在 `modules/` 底下，不受這條規則影響。

模型、reader、VLM 後端這些則可以自由換。

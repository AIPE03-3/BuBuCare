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

[`ai/export_models.py`](../ai/export_models.py) 從 `ai/` 底下的來源權重重建三顆：

| Triton 模型 | 來源權重 | 產出 |
|---|---|---|
| `yolo_pose` | `yolo11s-pose.pt` | `triton_repo/yolo_pose/1/model.onnx` |
| `rt_detr` | `rtdetr-l.pt`（首次執行 ultralytics 會自動下載）| `.../rt_detr/1/model.onnx` **＋ `model.plan`** |
| `action_transformer` | `action_transformer.pth`（要跟組員拿）| `.../action_transformer/1/model.onnx` |

⚠️ **`--plan` 不是選配**：這台的 `rt_detr` 是 `platform: tensorrt_plan`，只有 `model.onnx`
**Triton 會整支起不來**（explicit 模式一顆載入失敗會把另外兩顆一起拖垮，事故記錄見
[`ai/triton_repo/README.md`](../ai/triton_repo/README.md)）。`--plan` 會另開一個 Triton 官方鏡像的
容器跑 `trtexec` 編出這台 GPU 專屬的引擎，**要 4 分鐘左右**，慢是正常的。

TensorRT 引擎綁「GPU 架構 + TensorRT 版本」，**不能跨機器複製**，每台要自己編。
Mac 沒有 NVIDIA GPU 編不出來，走第四節的兩個選擇。

匯出參數（固定/動態 shape、opset）是照著已進版控的 `config.pbtxt` 反推的，不是上游預設值，
**不要隨手改**——對不上 Triton 會直接拒載。

`ai/test_demo/` 只有 test1~3.mp4（各約 1.5MB）；test4.mp4 是 FPS 量測長片，要用請另外跟人要。

### 3. MLOps 迴路（標註 → 重訓 → 熱部署）

那條迴路的服務、腳本與跑法另外寫在 [`ai/MLOPS.md`](../ai/MLOPS.md)，日常開發不需要起那些服務。

---

## 二、護欄擋什麼（`scripts/check_guardrails.py`）

| 擋 | 為什麼 |
|---|---|
| 家目錄絕對路徑 `/home/xxx/`、`/Users/xxx/` | 換一台機器就失效，這是兩邊互相弄壞對方最常見的原因 |
| 單檔 > 10MB | 模型/影片/資料集塞進 repo，push 不上去還要改寫歷史 |
| 明文密碼、AWS 金鑰 | 進了 git 就很難清乾淨 |
| `route_by_confidence()` 的 payload 欄位 | 後端 consumer 靠這組欄位寫 PostgreSQL，少一個就 422 退件 |
| `ai/modules/` 新增非白名單檔案、或 import 它們 | 哪些偵測模組在用是階段決策，見 `CLAUDE.md` |
| `ai/modules/` 底下的檔案自己 `.send(...)` | 模組自組 payload 外發＝繞過契約，實測每則都被後端 422 靜默丟棄 |

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

**完整的操作手冊在 [`RUN_ON_MAC.md`](RUN_ON_MAC.md)**（每次開機的啟動順序、埠表、症狀→解法），
做到哪裡與踩過的坑在 [`MAC_SETUP_WBS.md`](MAC_SETUP_WBS.md)。這裡只講骨架。

`ai/inference_test.py` 本身支援 Mac，但**三顆模型都打 Triton**，所以要有一個 Triton server
才跑得動。Mac 沒有 NVIDIA GPU，兩個選擇：

1. **Mac 上跑 CPU 版 Triton**（已在 M2 Pro 實測跑通全鏈，2.3~2.4 fps）。
   `run_triton.sh` 本來就支援 `TRITON_GPUS=none`，**不必改腳本**。但有兩個一定會撞到的點：

   - `ai/triton_repo/` 的 `config.pbtxt` 寫死 `instance_group kind: KIND_GPU`，沒 GPU 時
     三顆全 UNAVAILABLE、explicit 模式**一顆倒全倒**。要先跑 `./ai/make_cpu_repo.sh`
     產出 `ai/triton_repo_cpu/`（把 `KIND_GPU` 換成 `KIND_CPU`，權重走 hardlink，產物不進版控）。
   - `rt_detr` 是 `platform: tensorrt_plan`，Mac 編不出引擎。改打同一份權重的 ONNX 版
     `rt_detr_onnx`，用 `.env` 的 `TRITON_DETR_URL` 指過去就好，**不要改 `config.pbtxt`**
     （那會弄壞 5060 Ti 那台）。

2. **連到 5060 Ti 那台**（同網段/tailscale）：

   ```bash
   export TRITON_POSE_URL=grpc://<那台的IP>:8011/yolo_pose
   export TRITON_DETR_URL=grpc://<那台的IP>:8011/rt_detr
   export TRITON_ACT_URL=grpc://<那台的IP>:8011/action_transformer
   ```

FPS 數字不要跨機器比較，只在同一台上比前後差異。

---

## 五、分支流程

demo 以 5060 Ti 那台為準，所以定案的流程是**兩段式**：

```
從 test/main-integration 開自己的分支
        ↓  做完，發 PR
   test/main-integration          ← 在 5060 Ti 上實跑驗證
        ↓  驗過沒問題，再發一個 PR
        main                      ← 主幹，只收驗過的東西
```

規矩：

- **不要直接 push 到 `test/main-integration`，也不要直接 push 到 `main`**
- **新分支一律從 `test/main-integration` 開**，不要從 `main` 開
  （`main` 可能落後於已驗證的整合狀態，從那裡開會少掉別人剛驗過的東西）
- 功能 PR 一律先進 `test/main-integration`，**不要直接對 `main` 發 PR**
- `test/main-integration` → `main` 是獨立的一段，累積一批驗過的成果再合

PR 上 GitHub Actions 是綠燈才代表「沒踩到已知的雷」，不代表功能對；功能還是要在
5060 Ti 上實跑過。

### 合併時最容易踩的雷：「合乾淨」不等於「語意對」

2026-07-28 實際踩到：合併 `main` 時 `backend/devices/router.py` 與 `backend/init_db.py`
都是 **git 自動合併成功**的（兩邊改的是同一個檔的不同段落，diff 上完全看不出問題），
但一執行就 `TypeError: 'stream_url' is an invalid keyword argument`
——因為另一邊把那個欄位改名了。

所以合併後**不能只看有沒有衝突標記**：

1. 跑全套測試（`backend` pytest、`agent` pytest、`npx tsc -b`）——
   backend 平常用 `cd backend && uv run pytest`（見 `backend/CLAUDE.md`），但那顆 venv
   在 `nh-backend` 容器管理範圍外時常沒建好；host 另建一顆 `.venv-backend`
   （`python -m venv .venv-backend` + 裝 `backend/pyproject.toml` 的 `[project.dependencies]`
   加 `pytest`）可以在 repo 根目錄直接 `.venv-backend/bin/python -m pytest backend -q` 驗證，
   不必進容器也不用改 `nh-backend` 的 image
2. 跑 `python3 scripts/check_guardrails.py`
3. **實際起服務打 API** —— 上面那個 bug 三種測試都測不出來，是打 `POST /devices` 才炸的

這類破口 code review 抓不到，因為程式碼本身看起來很合理。

---

## 六、不能動的東西

- **Kafka topic 名稱**：`processed-reports`、`nursing-home-alerts`
- **`route_by_confidence()` 的 payload 欄位**（護欄會擋）

這兩個是跟後端組講好的契約邊界。要改必須兩邊同時改，不是「我這邊跑得動」就算數。

- **`ai/modules/` 的模組不准自組 payload 送 Kafka**（護欄 `check_module_no_kafka()` 會擋）。
  模組只負責偵測、回傳訊號，外發統一交給主迴圈的 `route_by_confidence()`——範本是
  `chair_slip.py`。這條**沒有階段性**，是契約邊界。

至於「哪些檔可以存在」（`ai/modules/` 白名單）則是**會隨階段決策變動**的，目前放行四個：
`__init__.py`、`sanity_check.py`、`bed_exit.py`、`chair_slip.py`。2026-07-30 起離床與座椅
滑落收回研究，遊走 / 躁動 / 音訊融合維持封印。**檔案本身不在版控中**，要從歷史撈回來，
指令與兩個檔的差異（`bed_exit.py` 復活後會被護欄擋，要先改）見 [`CLAUDE.md`](../CLAUDE.md)。

跌倒主邏輯在 `ai/inference_test.py` 主迴圈，不在 `modules/` 底下，不受這兩條規則影響。

模型、reader、VLM 後端這些則可以自由換。

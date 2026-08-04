# AcT v2 上線：Triton 換版與實測

日期：2026-08-04
分支：`feat/act-v2-deploy`（未 push）
影響範圍：**只有本機的 Triton model repository**。程式碼一行未改。
前置文件：[2026-07-29-act-retrain-results.md](2026-07-29-act-retrain-results.md)（重訓成果）

---

## TL;DR

`action_transformer` 從 v1 換成 v2，Triton 三顆全程 READY、服務未中斷。

在 `ai/test_demo/` 的實測影片上，v2 同時做到**少誤報**與**少漏報**：

| 影片 | 內容（**逐幀看過畫面確認**）| v1 觸發 | v2 觸發 | 判讀 |
|---|---|---:|---:|---|
| `test6.mp4` | 教室俯視，**10.0s 有人跌倒** | 85/158 | **20/158** | v1 在 **4.02s** 就報 —— 真跌倒發生前 **6 秒**的誤報。v2 首次觸發 10.71s，延遲約 0.7 秒 |
| `test7.mp4` | 教室俯視，**14.5s 起才有人在地上** | 152/205 | **47/205** | v1 從 4.41s 連燒到 14.57s，整整 **10 秒**畫面上沒人倒地。v2 把這段清掉，保留 14.5s 之後的真事件 |
| `test8.mp4` | 走廊，**7.5s 有人倒下、13s 才爬起來** | **1/124** | **21/124** | v1 只在 15.97s 報一幀（人早就站起來了）＝**漏報**。v2 從 7.45s 報到 9.98s，正中事件 |
| `test2/3/5` | — | 各 10 / 14 / 42 | **完全相同** | 這三支的觸發全由幾何防線決定，AcT 不是決定因素 |
| `test1.mp4` | — | 0 | 0 | **不是結果，是讀不到**：AV1 編碼（`libdav1d`），OpenCV 解不動。見下方「限制」 |

一句話：**v1 在該報的時候不報（test8）、不該報的時候報（test6 早了 6 秒、test7 燒了 10 秒），v2 三項都修好了。**

---

## 一、做了什麼

### 1. 轉 ONNX（開新版本目錄，沒有覆蓋 `1/`）

```bash
ai/.venv/bin/python ai/train/export_onnx.py \
  --weights ai/action_transformer_v2.pth \
  --out ai/triton_repo/action_transformer/2/model.onnx
```

輸出原文：

```
💾 /home/rapubuntu/aipe03-3/ai/triton_repo/action_transformer/2/model.onnx（308 KB）
🔍 PyTorch vs ONNX 最大絕對差：2.38e-07
✅ 數值一致
```

| 檔案 | 大小 | sha256（前 16 碼）|
|---|---:|---|
| `ai/action_transformer.pth`（v1 權重）| 295 KB | `0c912a147c5c90c3` |
| `ai/action_transformer_v2.pth`（v2 權重）| 295 KB | `4d50397c58f7dcbe` |
| `ai/triton_repo/action_transformer/1/model.onnx` | 315702 B | 保留不動（回滾路徑）|
| `ai/triton_repo/action_transformer/2/model.onnx` | 315702 B | `65cea5dfe8f77a5b` |

### 2. 改 `version_policy` 並熱載

`ai/triton_repo/action_transformer/config.pbtxt` 最後一行，
先改成 `versions: [ 1, 2 ]`（兩版並存才能做同輸入對照），量完再收斂成 `versions: [ 2 ]`。
兩次都用 `POST /v2/repository/models/action_transformer/load` 熱載，回 HTTP 200。

換版前後的 `POST /v2/repository/index`：

```
# 前
[{"name":"action_transformer","version":"1","state":"READY"},
 {"name":"rt_detr","version":"2","state":"READY"},
 {"name":"yolo_pose","version":"1","state":"READY"}, ...]

# 後
[{"name":"action_transformer","version":"1","state":"UNAVAILABLE","reason":"unloaded"},
 {"name":"action_transformer","version":"2","state":"READY"},
 {"name":"rt_detr","version":"2","state":"READY"},
 {"name":"yolo_pose","version":"1","state":"READY"}, ...]
```

三顆的 `/v2/models/<name>/ready` 全部 200。
per-version 探針：`action_transformer/versions/1/ready` → **400**（已不服務）、
`versions/2/ready` → **200**。

---

## 二、驗證（四層，由淺到深）

### L1 匯出正確性：PyTorch vs ONNX

`export_onnx.py` 內建，最大絕對差 **2.38e-07**，容許值 1e-4。**通過。**

### L2 serving 正確性：Triton vs 本機 PyTorch

用 `test6`/`test7` 抽出的 **120 個真實 pose 特徵視窗**（不是隨機數 —— 隨機輸入落在
訓練分布之外，數值差異不代表實際 serving 的差異）：

| | 最大 logit 絕對差 | 門檻 1e-2 |
|---|---:|---|
| Triton v1 vs 本機 `action_transformer.pth` | 1.309e-02 | ⚠️ 略超 |
| **Triton v2 vs 本機 `action_transformer_v2.pth`** | **4.352e-03** | ✅ 通過 |
| （交叉檢查）Triton v1 vs Triton v2 | 5.499e+00 | ← 遠大於門檻，確認兩版真的是不同模型 |

門檻取自 [`ai/verify_backend_parity.py:42`](../verify_backend_parity.py) 的
`THRESH["act_logit"] = 1e-2`。

### L3 判定層：那個 1.3e-2 有沒有改變任何決策

L2 的 v1 略超門檻，所以直接驗該門檻註解寫的那句話
（「logits 差 0.01 內，softmax 後對 class 判定無影響」）：

| | argmax 不一致 | softmax 機率最大差 | 0.55 觸發線判定不一致 |
|---|---:|---:|---:|
| v1 | **0/120** | 5.638e-03 | **0/120** |
| v2 | **0/120** | 6.813e-04 | **0/120** |

0.55 是正式管線的直接觸發線（[`ai/inference_test.py:1110`](../inference_test.py)）。
**兩版在 Triton 與本機之間沒有任何一筆決策不同**，v1 那個 1.3e-2 是無害的；
v2 的 parity 還比 v1 緊 8 倍。

### L4 管線層 A/B：換版真的改變了什麼

同一份 pose 串流、只換 AcT 權重：

```bash
ai/.venv/bin/python ai/local_pipeline_eval.py ai/test_demo/test<N>.mp4 \
  --act-weights ai/action_transformer{,_v2}.pth \
  --trigger-mode current --occ-height 0.70 --multi-person --no-show --csv <out>.csv
```

> ⚠️ 那三個參數**不能省**，理由見下方「發現三」。

觸發來源拆解（幾何＝`is_lying`／`is_occluded` 成立；AcT 獨力＝幾何全正常、只有 AcT 說跌倒）：

| 影片 | 版本 | 觸發 | 幾何 | AcT 獨力 | 觸發時間區間 |
|---|---|---:|---:|---:|---|
| test2 | v1／v2 | 10／10 | 10／10 | 0／0 | 5.95s 起，兩版相同 |
| test3 | v1／v2 | 14／14 | 14／14 | 0／0 | 4.03s 起，兩版相同 |
| test5 | v1／v2 | 42／42 | 42／36 | 0／6 | 5.44s 起，兩版相同 |
| **test6** | v1 | 85 | 9 | **76** | `4.02~14.06s`  18.34s  `19.41~20.88s` |
| | **v2** | **20** | 11 | **9** | **`10.71~12.32s`**  18.34s  `19.41~20.88s` |
| **test7** | v1 | 152 | 30 | **122** | 0.27~0.80s … **`4.41~15.64s`** … |
| | **v2** | **47** | 30 | **17** | 0.27~0.80s … **`14.57~15.64s`** … |
| **test8** | v1 | **1** | 1 | 0 | `15.97s` 單一幀 |
| | **v2** | **21** | 2 | **19** | **`7.45~9.98s`**  15.97s |

**AcT 獨力觸發：test6 76→9（−88%）、test7 122→17（−86%）、test8 0→19（從無到有）。**
幾何觸發的部分幾乎不動（那本來就跟 AcT 無關），證實差異全部來自換版。

---

## 三、ground truth 是怎麼確認的

上表的「該不該報」不是從檔名推的，是**實際把畫面抽出來看**。
可重現：`cv2.VideoCapture` + `CAP_PROP_POS_FRAMES` 取指定秒數的幀。

| 影片 | 時間點 | 畫面內容 |
|---|---|---|
| `ai/test_demo/test6.mp4` | 4.0s | 教室，三人站／坐，**無人倒地** → v1 此時觸發是誤報 |
| | 8.0s | 全員站立 |
| | 10.0s | 一人正在往下（跌落起始）|
| | 10.7s | 該人**已在地上** → v2 首次觸發落在此區間 |
| `ai/test_demo/test7.mp4` | 5.0／8.0／11.0／13.5s | **四個時間點全員站立、無人在地** → v1 這段連續觸發是誤報 |
| | 15.0s | 有人蹲下／伏地 |
| | 17.5s | **兩人在地上** → v2 保留的觸發對得上 |
| `ai/test_demo/test8.mp4` | 3.0s | 走廊，兩人正常行走 |
| | 7.5s | 一人正在倒下 |
| | 10.0s | 該人**整個趴在地上** |
| | 13.0s | 已站起走動 → v1 唯一那幀（15.97s）在此之後，等於沒抓到 |

---

## 四、四個發現（都不在原本的計畫裡）

### 發現一：`action_transformer` 的鎖版設定，先前根本沒生效

Triton 容器啟動於 `2026-07-29T09:02:33Z`，而 `config.pbtxt` 裡
`version_policy: { specific { versions: [ 1 ] } }` 那一行的 mtime 是 `2026-08-03 19:20`。
**設定是容器起來之後才加的，容器從沒重讀過。** 換版前查到的實際生效值是：

| 模型 | 磁碟上的 config.pbtxt | 容器內實際生效 |
|---|---|---|
| `rt_detr` | `specific [2]` | `specific [2]` ✅（啟動前就在檔案裡）|
| **`action_transformer`** | `specific [1]` | **`latest { num_versions: 1 }`** ❌ |
| `yolo_pose` | 無 | `latest { num_versions: 1 }`（相符，本來就沒鎖）|

`latest` 就是 [`ai/triton_repo/README.md`](../triton_repo/README.md) 事故記錄裡
**2026-07-26 讓整台 Triton 起不來的那個行為**（自動載版本號最大的目錄）。
也就是說在本次 `POST /load` 之前，那條鐵則對這顆模型是失效的。

**教訓：改了 `config.pbtxt` 不 reload，等於沒改。** 現在已隨換版一併生效。

### 發現二：`/v2/models/<name>/config` 回報的 `version_policy` 會落後

收斂成 `[ 2 ]` 並 reload 兩次之後，該端點仍回報 `{'specific': {'versions': [1, 2]}}`，
但 `repository/index` 與 per-version ready 探針都正確反映只服務 v2。

**要判斷實際服務哪一版，看 `POST /v2/repository/index` 或
`GET /v2/models/<name>/versions/<v>/ready`，不要看 config 端點。**

### 發現三：`local_pipeline_eval.py` 的預設值與正式管線不一致

該檔多處註解寫「對齊正式管線」，實際不是：

| | `local_pipeline_eval.py` 預設 | `ai/inference_test.py` 實際 |
|---|---|---|
| 觸發策略 | `geo-first`（`act_alone=False`）:141 | **`current`**（`act_alone=True`）:1108-1110 |
| 遮擋高度門檻 | `0.50` :105 | **`0.70`** :1012 |
| 多人 | 預設單人（:652 註解寫「正式管線目前是單人」）| **多人**（`person_fall_flags` + tracker）|

用預設值跑出來的數字**不是正式管線的行為**。本次 A/B 全部顯式帶
`--trigger-mode current --occ-height 0.70 --multi-person`。
**本輪沒有修這個落差**（那是評估工具的問題、不是部署的問題），但下次動它之前要知道。

順帶一提：因為正式管線的 `act_alone=True` 本來就開著
（[`inference_test.py:1110`](../inference_test.py)），
換權重會**直接**改變線上行為，不需要另外開任何旗標。
[2026-07-29-act-retrain-results.md](2026-07-29-act-retrain-results.md) 說
「`ACT_ALONE_CAN_TRIGGER` 未打開」對現在這份程式碼已經不成立。

### 發現四：`verify_backend_parity.py` 換版後會誤判失敗

它的 `LocalActModel()`（[:122](../verify_backend_parity.py)）沒有權重參數，
寫死讀 `ai/action_transformer.pth`（v1）。Triton 換成 v2 之後，這支會拿 v2 的輸出
去跟 v1 的權重比，`act_logit` 必定超門檻 —— **那是工具的問題，不是部署壞掉**。

本輪沒改這支工具，L2／L3 用臨時腳本做同一件事。
要修的話，給它一個 `--act-weights` 參數即可。

---

## 五、限制：哪些數字不能過度解讀

- **`test1.mp4` 完全沒被評估到。** 它是 AV1（`libdav1d`），`local_pipeline_eval.py`
  直接用 `cv2.VideoCapture`，讀不到任何一幀（輸出「讀取到第 0 幀」）。
  repo 裡有 [`ai/av_reader.py`](../av_reader.py) 專門處理這件事，但評估工具沒接。
  表上的「0 觸發」是讀不到，不是判定結果。
- **樣本數小。** 六支有效影片、三場景，其中真跌倒事件只有 3 次（test6、test7、test8 各一段）。
  方向可信，倍數不可外推。
- **`test8` 的 15.97s 那一幀兩版都報**，是幾何觸發，跟 AcT 無關。
- **沒有做隔離評估。** CAUCAFall 影片不在這台機器上
  （`ai/train/dataset/videos/` 是空的、沒有任何 `.npz` 特徵快取），所以
  `ai/train/evaluate_act.py` 跑不起來 —— 那才是能跟重訓報告數字直接對照的評估。
  影片備齊後補跑，見下方「還沒做的」。
- `ai/batch_eval.py` 在這台機器上沒有用：它的 `SKIP_PREFIXES = ("test",)` 會把
  `test_demo/` 八支全部跳過，找不到目標直接 return 1。

---

## 六、⚠️ `config.pbtxt` 的版本號改動不進版控

`ai/triton_repo/action_transformer/config.pbtxt` 現在是
**「已修改、未提交」的狀態，這是刻意的，不要順手 commit。**

理由：權重目錄 `ai/triton_repo/*/[0-9]*/` 被 `.gitignore:61` 排除，不進版控。
這台鎖 v2、別人機器只有 `1/` 的話，他 pull 下去那顆模型就 UNAVAILABLE，
而 explicit 模式**一顆倒全倒**，整台 Triton 起不來
（`rt_detr` 2026-07-26 踩過，記錄在 [`ai/triton_repo/README.md`](../triton_repo/README.md)）。

本次只 commit 這一份 `.md`。驗證：`git show --stat HEAD` 應只有這個檔。

**別台機器要跟上 v2 的做法**：把 `ai/action_transformer_v2.pth` 拿到手，
在自己機器上跑第一節那行 `export_onnx.py`，再自己改 `config.pbtxt` 並 reload。

---

## 七、回滾

```bash
python ai/model_deployment_agent.py --rollback     # v2 → v1，改 config 並熱載
```

`1/model.onnx` 保留未動，這條路走得通。
（注意：這支的 `VERSION_RE` 只認單一版本號，中途那個 `[ 1, 2 ]` 狀態它讀不出來。
現在已收斂成 `[ 2 ]`，可以正常用。）

---

## 八、驗證指令與結果

```
python scripts/check_guardrails.py       → ✅ 護欄檢查通過（掃了 437 個檔案）
python -m pytest agent ai scripts -q     → 191 passed in 4.45s
curl -s -X POST :8010/v2/repository/index → action_transformer v2 READY
                                            rt_detr v2 READY / yolo_pose v1 READY
git status --short                        → 只有 M ai/triton_repo/action_transformer/config.pbtxt（不提交）
```

---

## 九、還沒做的

1. **隔離評估**（等 CAUCAFall 影片）：影片放 `ai/train/train_data/` →
   `build_dataset.py` → `extract_features.py --splits test` →
   `evaluate_act.py --models ai/action_transformer.pth ai/action_transformer_v2.pth`。
   `ai/train/dataset/labels/` 已有 50 份人工逐幀標註，可算出跌倒召回／**前跌召回**／
   正常誤報／跌完躺著誤報四項，與重訓報告一比一對照。
2. **端到端實跑**（本輪刻意不做）：`SINGLE_SOURCE=ai/test_demo/test8.mp4` 走完整條
   Kafka → 後端鏈。本輪決定不外發到共用 RDS／S3。
3. 發現三、四的兩個工具落差（`local_pipeline_eval.py` 預設值、
   `verify_backend_parity.py` 權重寫死）**本輪只記錄未修**。

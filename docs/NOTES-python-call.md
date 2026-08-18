# 學習筆記：`__call__` — 這個專案怎麼做到「換模型不改主程式」

> 2026-08-04 整理。屬於**個人學習筆記**，不是規格文件——要查契約與硬規則請看
> [`../CLAUDE.md`](../CLAUDE.md) 與 [`ARCHITECTURE.md`](ARCHITECTURE.md)。
>
> 對應原始碼：[`ai/triton_pose_client.py`](../ai/triton_pose_client.py)、
> [`ai/triton_detr_client.py`](../ai/triton_detr_client.py)、
> [`ai/triton_act_client.py`](../ai/triton_act_client.py)、
> [`ai/inference_test.py`](../ai/inference_test.py)（第 510-582 行載入三顆模型那段）

---

## 一、`__call__` 是什麼

Python 的一條規則：

> **物件身上有 `__call__`，這個物件就能加括號、像函式一樣呼叫。**

```python
class 打招呼:
    def __call__(self, 名字):
        return f"你好，{名字}"

hi = 打招呼()      # hi 是「物件」，不是函式
hi("小明")         # 但可以加括號 → Python 背地裡跑的是 hi.__call__("小明")
```

`__call__` 就是「這個物件被加括號時要跑哪段程式」。

---

## 二、這個專案為什麼需要它

**問題**：模型要從「本機硬碟權重」搬到「Triton server」（另一個行程、走 HTTP），
但 `ai/inference_test.py` 有 1500 行，不想動。

**解法**：做一個替身，長得跟 ultralytics 官方的 `YOLO` 一模一樣。

```python
# yolo_pose_model = YOLO("yolo11s-pose.pt")          ← 舊的
yolo_pose_model = TritonPoseModel(TRITON_POSE_URL)   # ← 只改這一行

results_pose = yolo_pose_model(frame, conf=0.45)     # 底下一個字沒動
kpts = results_pose[0].keypoints.xyn
```

### 「長得一樣」要同時滿足兩件事

| 要求 | 怎麼做到 | 在哪 |
|---|---|---|
| 呼叫方式一樣 | 實作 `__call__` | `triton_pose_client.py:52` |
| **回傳東西也一樣** | 最後包回 `Results` 物件 | `triton_pose_client.py:96` |

**兩個都對才騙得過去。** 只做前面那個，下游讀 `.keypoints` / `.boxes` 一樣會爆，
還是得回去改那 1500 行。

這種「不看你是什麼類別、只看你能不能被這樣用」的作風，叫 **duck typing（鴨子型別）**。

---

## 三、點餐窗口比喻

```python
results_pose = yolo_pose_model(frame, conf=0.45)
                     ↑            ↑
                   廚房        點餐內容
```

| 角色 | 是誰 |
|---|---|
| **客人** | 主程式 `inference_test.py`（說出這行的人，不出現在這行裡） |
| **窗口** | `( )` 這對括號，也就是 `__call__` |
| **廚房** | `yolo_pose_model`（本地？Triton？MPS？從這行看不出來） |
| **餐點** | `results_pose`（一個 `Results` 物件） |

> 只要**窗口規格不變**（怎麼點、拿到什麼），廚房整個換掉客人都無感。

⚠ 常見的角色錯位：**模型不是電器，模型是廚房。** 要服務的是主程式，
提供服務的是模型。方向搞反了整個比喻就歪了。

---

## 四、比「到處寫 if」高明在哪

### if 方法的真正問題：這個 if 會傳染

三種來源回傳的格式不同 → 下游**每一個讀資料的地方都得跟著分岔**。
讀人框要分岔、讀信心值要分岔、畫圖要分岔。一個 if 生出十個 if。

而且它**每一幀都要重新問一次**——一秒 30 幀 × 四台相機 = 一秒問 120 次
「我到底是哪種後端」，而答案從開機到關機都一樣。

### `__call__` 方法：開機問一次就丟掉

實際程式在 `inference_test.py:532-543`：

```python
_POSE_BACKEND = cfg("POSE_BACKEND", "triton")   # 讀環境變數

if _POSE_BACKEND == "mps":
    yolo_pose_model = build_pose_model(_POSE_WEIGHTS)   # 本地 Apple GPU
elif _POSE_BACKEND == "triton":
    yolo_pose_model = TritonPoseModel(TRITON_POSE_URL)  # 打 Triton
```

**if 只出現在這一處，開機時跑一次。**

### 對照表

| | if 方法 | `__call__` 方法 |
|---|---|---|
| 何時問「用哪個後端」 | 每一幀都問 | 開機問一次 |
| 加新後端要改幾處 | 所有分岔點 | 一處 |
| 漏改會怎樣 | **靜默走錯路徑，不報錯** | 不會漏 |
| 讀 code 的負擔 | 腦中一直要維護「我在哪條分支」 | 直線讀下去 |

### 第三列為什麼最可怕：專案的真實事故

`inference_test.py:517-519` 記著一個踩過的坑——Triton 的埠號預設值曾寫成 8000
（那個埠被 backend 佔用）：

> 每一幀都打到 FastAPI、拿回 `{"detail":"Not Found"}` 後**靜默降級**——
> 影片照跑、FPS 照印、沒有紅字，但姿態偵測全程失效。

**分岔越多，這種「看起來在跑、其實是壞的」的洞就越多。**

> 核心差別：**if 讓「差異」在程式裡到處流竄；`__call__` 把「差異」關進盒子封起來。**
> 這個動作的正式名稱是 **封裝（encapsulation）**。

---

## 五、為什麼是「物件 + `__call__`」而不是純函式

因為**物件記得住東西**（`triton_pose_client.py:38-42`）：

```python
def __init__(self, triton_url, imgsz=640, iou=0.7):
    self._triton_url = triton_url      # 記住：要打哪個網址
    self._imgsz = imgsz                # 記住：圖要縮到多大
    self._iou = iou                    # 記住：NMS 門檻
    self._local = threading.local()    # 記住：這條執行緒的連線 ← 最值錢的
```

純函式的話每次呼叫都要重複交代：

```python
results = triton_pose推論(frame, "http://127.0.0.1:8010/yolo_pose", 640, 0.7, conf=0.45)
#                              └────────── 每一幀都要傳的一堆設定 ──────────┘
```

而且**沒地方存連線**——每一幀都得重建 HTTP 連線。物件可以把連線存在
`self._local`，建一次用到死。

### 三種寫法比較

| | 純函式 | 純物件（寫成 `.predict()`） | 物件 + `__call__` |
|---|---|---|---|
| 用起來簡單 | ✅ | ❌ 每次要記方法名 | ✅ |
| 記得住設定 | ❌ | ✅ | ✅ |
| 記得住連線 | ❌ | ✅ | ✅ |
| **能假扮成 `YOLO`** | ❌ | ❌ | ✅ |

最後一列是關鍵：**官方 `YOLO` 就是「加括號直接呼叫」，替身必須是同一個形狀。**
寫成 `model.predict(frame)` 的話，主程式那 1500 行還是要改。

**結論：外表是函式（好用），內在是物件（有記憶）。**

---

## 六、專案裡三個實際用途

| 用途 | 環境變數 | 效果 |
|---|---|---|
| **切後端** | `POSE_BACKEND=triton` / `mps` | Mac 上 pose 走 Apple GPU，2.3 fps → 28.8 fps |
| **關功能** | `DETR_ENABLED=0` | `yolo_env_model = None`，下游靠 None guard |
| **降級** | （自動） | Triton 掛掉時 AcT 退回幾何模擬，主迴圈照跑 |

三顆模型全部用同一個模板：

| 檔案 | 假扮成誰 | 回傳 |
|---|---|---|
| `triton_pose_client.py` | `YOLO("yolo11s-pose.pt")` | `[Results]` |
| `triton_detr_client.py` | `RTDETR("rtdetr-l.pt")` | `[Results]` |
| `triton_act_client.py` | 本地 torch 模型 | 原始 logits `(1,2)` |

第三個特別注意：AcT 刻意**回傳原始 logits 而不是處理好的 `(類別, 信心)`**，
這樣下游 `torch.softmax` / `torch.argmax` 那兩行也一字不用改。

> 設計 API 的心得：**回傳「最原始的東西」比回傳「幫你處理好的東西」更容易被接上。**
> 原始資料下游想怎麼處理都行；處理過的資料，下游想要別的就沒轍了。

---

## 七、一句話帶走

> **`__call__` 把「換引擎」的成本，從改一千行壓到改一行。**

呼應 `CLAUDE.md` 第六節的 Linus 原則：

> **好品味就是把特殊情況消滅掉，變成正常情況。**
>
> 不是寫更聰明的 if，是讓 if 根本沒必要存在。

---

## 待補（下一個主題）

- `threading.local()` 與 `greenlet.error: Cannot switch to a different thread`
  ——為什麼連線不能在主執行緒建好共用

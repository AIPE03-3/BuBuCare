"""AcT 輸入特徵的唯一定義。

## 為什麼要獨立成一個模組

34 維特徵 `kp[:17, :2].flatten()` 原本在三個檔案各寫了一份：

| 檔案 | 角色 |
|---|---|
| `inference_test.py` | 正式推論管線 |
| `local_pipeline_eval.py` | 本機評估、**訓練特徵抽取也走這裡** |
| `local_pose_eval.py` | 姿態診斷工具 |

三份程式碼、零份約束。改了其中一份而漏掉另一份，**不會有任何症狀**：
shape 一樣是 (34,)、dtype 一樣是 float32、模型照樣吐得出信心值——
只是訓練時看到的向量與推論時看到的已經是不同語意（train/serve skew）。
指標會莫名其妙變差，而且查不到原因。

所以特徵定義只能有一個來源。要換正規化方式，改這裡，各處自動同步。

## 兩種正規化

| 模式 | 座標基準 | 模型看得到 |
|---|---|---|
| `image`（預設、現行） | 整張畫面 | 人在畫面的哪個位置、佔多大 |
| `bbox` | 人物框 | 只有身體各部位的相對關係 |

`image` 下「人躺下 → 骨架整體往畫面下方掉」是強訊號，模型很可能重度依賴它。
但**俯視鏡頭下這個訊號不存在**：人跌倒後在畫面上的位置幾乎不動。
`bbox` 把絕對位置整個拿掉，強迫模型學姿勢本身。代價是丟掉「人在低處、
人變矮」這兩個線索——但那本來就由幾何防線 A/B 負責，AcT 不需要重複學。

哪個好是實證問題，不是設計問題。故兩者並存，由呼叫端明示選哪個。

## ⚠ 模式必須跟權重綁在一起

同一份權重只在「訓練時用的那個模式」下有意義。用 `image` 訓練的模型餵
`bbox` 特徵，shape 一樣、不會報錯、照樣吐信心值，但輸出全是垃圾。

所以：
  - `extract_features.py` 把模式寫進 `features/*.npz` 的 `feature_norm`
  - `train_act.py` 拒絕混用不同模式的 npz，並把模式寫進 `<權重>.run.json`
  - `evaluate_act.py` 比對兩者，不一致就擋下來

不要靠人記得設對。
"""

import numpy as np

# COCO 17 點，每點取 (x, y)。AcT 的 Linear(34→64) 綁死這個數字，改了要連模型一起改
KEYPOINT_COUNT = 17
FEATURE_DIM = KEYPOINT_COUNT * 2

FEATURE_NORM_IMAGE = "image"
FEATURE_NORM_BBOX = "bbox"
FEATURE_NORMS = (FEATURE_NORM_IMAGE, FEATURE_NORM_BBOX)
DEFAULT_FEATURE_NORM = FEATURE_NORM_IMAGE


def empty_feature():
    """沒有可用人物時的佔位向量。等同「這幀沒偵測到人」。"""
    return np.zeros(FEATURE_DIM, dtype=np.float32)


def is_feature_valid(feature):
    """全零＝關鍵點整組沒抓到，餵給 AcT 也是廢的。

    ⚠ `xyn` 的 0 是「沒抓到」的哨兵值，不是「在畫面左上角」。
    """
    return bool(not np.all(np.asarray(feature) == 0))


def pose_feature_image_norm(keypoints_norm):
    """對整張畫面正規化——直接用 `keypoints.xyn`，不做任何轉換。

    keypoints_norm: (>=17, >=2) 的 `xyn` 陣列。
    """
    return np.asarray(keypoints_norm)[:KEYPOINT_COUNT, :2].flatten().astype(np.float32)


def pose_feature_bbox_norm(keypoints_norm, box_xyxyn):
    """對人物框正規化——把關鍵點換算成「在框內的相對位置」。

    keypoints_norm: (>=17, >=2) 的 `xyn` 陣列。
    box_xyxyn: 同一人的 `boxes.xyxyn`，(4,)。**必須跟關鍵點同一個座標系**
        （兩者都對整張畫面正規化），否則算出來是垃圾。

    框寬或框高為 0 時回全零（視同無效幀）——除以 0 會產生 inf/nan，
    那會一路污染到模型輸入，寧可當作這幀沒抓到人。

    ⚠ 不裁切到 [0, 1]：YOLO 有可能把關鍵點預測在框外（手伸出去、框抓太緊），
       那是真實資訊，裁掉反而抹平差異。
    """
    keypoints = np.asarray(keypoints_norm, dtype=np.float32)[:KEYPOINT_COUNT, :2]
    x1, y1, x2, y2 = (float(v) for v in np.asarray(box_xyxyn, dtype=np.float32)[:4])
    width, height = x2 - x1, y2 - y1
    if width <= 0 or height <= 0:
        return empty_feature()

    # 沒抓到的點是 (0, 0) 哨兵值，不是座標。先記下來，換算完再蓋回去，
    # 否則 (0-x1)/w 會變成一個看起來很正常的負數，「缺點」這個資訊就消失了。
    missing = (keypoints[:, 0] == 0) & (keypoints[:, 1] == 0)
    feature = np.empty_like(keypoints)
    feature[:, 0] = (keypoints[:, 0] - x1) / width
    feature[:, 1] = (keypoints[:, 1] - y1) / height
    feature[missing] = 0.0
    return feature.flatten().astype(np.float32)


def pose_feature(keypoints_norm, box_xyxyn=None, feature_norm=DEFAULT_FEATURE_NORM):
    """依 `feature_norm` 分派到上面兩個函式之一。

    `bbox` 模式沒給 `box_xyxyn` 直接爆——那代表呼叫端漏接了框，
    靜默退回 `image` 只會製造出「看起來有跑、其實模式不對」的資料。
    """
    if feature_norm == FEATURE_NORM_IMAGE:
        return pose_feature_image_norm(keypoints_norm)
    if feature_norm == FEATURE_NORM_BBOX:
        if box_xyxyn is None:
            raise ValueError("feature_norm='bbox' 需要 box_xyxyn，呼叫端沒給")
        return pose_feature_bbox_norm(keypoints_norm, box_xyxyn)
    raise ValueError(f"未知的 feature_norm：{feature_norm!r}，可用：{FEATURE_NORMS}")


def check_feature_norm(name):
    """驗證模式名稱，回傳正規化後的字串。給 CLI 參數與 npz/run.json 讀取用。"""
    text = str(name).strip().lower()
    if text not in FEATURE_NORMS:
        raise ValueError(f"未知的 feature_norm：{name!r}，可用：{FEATURE_NORMS}")
    return text

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

所以特徵定義只能有一個來源。要換正規化方式，改這裡，三處自動同步。

## 目前的正規化

用 ultralytics 的 `keypoints.xyn`，對**整張畫面**正規化（不是對人物框）。
代表模型看得到「人在畫面的哪個位置、佔多大」——側視鏡頭下這是強訊號，
但換成俯視鏡頭就不成立。詳見 `ai/docs/2026-07-29-act-retrain-results.md`。
"""

import numpy as np

# COCO 17 點，每點取 (x, y)。AcT 的 Linear(34→64) 綁死這個數字，改了要連模型一起改
KEYPOINT_COUNT = 17
FEATURE_DIM = KEYPOINT_COUNT * 2


def pose_feature(keypoints_norm):
    """把單一人物的關鍵點壓成 AcT 的 34 維輸入。

    keypoints_norm: (>=17, >=2) 的 `xyn` 陣列，已對整張畫面正規化。
    回傳 float32 的 (34,) 向量。
    """
    return np.asarray(keypoints_norm)[:KEYPOINT_COUNT, :2].flatten().astype(np.float32)


def empty_feature():
    """沒有可用人物時的佔位向量。等同「這幀沒偵測到人」。"""
    return np.zeros(FEATURE_DIM, dtype=np.float32)


def is_feature_valid(feature):
    """全零＝關鍵點整組沒抓到，餵給 AcT 也是廢的。

    ⚠ `xyn` 的 0 是「沒抓到」的哨兵值，不是「在畫面左上角」。
    """
    return bool(not np.all(np.asarray(feature) == 0))

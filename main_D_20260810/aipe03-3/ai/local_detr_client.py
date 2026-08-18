"""本地版 RT-DETR client —— `triton_detr_client.TritonDetrModel` 的對照組。

存在的唯一理由是效能對照（見 ai/BENCHMARK_TRITON_VS_LOCAL.md）。生產路徑仍是 Triton 版。

介面與 `TritonDetrModel` 相同：`model(frame, conf=..., verbose=...)` -> `[Results]`，
另提供 `.names`（下游 `yolo_env_model.names[cls_id]` 要用）。

⚠️⚠️ **這顆與 Triton 上那顆不是同一個模型，數字不能直接算「Triton overhead」**：

| | Triton 的 `rt_detr` | 本地這支 |
|---|---|---|
| 權重 | v2 重訓版，**5 類**（person/chair/sofa/bed/tv，見 ai/data.yaml）| `rtdetr-l.pt`，**COCO 80 類** |
| 格式 | TensorRT plan（Blackwell 專屬編譯）| PyTorch |

類別數不同 → decoder 輸出維度與後處理成本不同；格式不同 → TensorRT vs PyTorch 是
另一個變因。所以對照文件把這顆放**附表**、標明「上線配置對照」，主表只用
yolo_pose 與 action_transformer（那兩顆兩邊確實同權重同來源）。

要讓這顆也變成單一變因，得把 v2 的 `.pt` 撈出來當本地權重
（`ai/model_deployment_agent.py` 從 ClearML 拉的那份），屬於下一輪的事。
"""
import os
import threading

import numpy as np
from ultralytics import RTDETR

_AI_DIR = os.path.dirname(os.path.abspath(__file__))
IMGSZ = 640
DEFAULT_WEIGHTS = os.path.join(_AI_DIR, "rtdetr-l.pt")

# 與 triton_detr_client.NAMES 同一個來源（COCO 80 類）。只讀 metadata、不做推論。
NAMES = RTDETR(DEFAULT_WEIGHTS).names


class LocalDetrModel:
    """呼叫介面比照 `TritonDetrModel`。thread-local 持有各自的 `RTDETR` 實例
    （理由同 local_pose_client.LocalPoseModel）。"""

    def __init__(self, weights: str = DEFAULT_WEIGHTS, imgsz: int = IMGSZ):
        if not os.path.isfile(weights):
            raise FileNotFoundError(f"找不到 rt_detr 權重：{weights}")
        self._weights = weights
        self._imgsz = imgsz
        self.names = NAMES
        self._local = threading.local()

    @property
    def _model(self) -> RTDETR:
        m = getattr(self._local, "model", None)
        if m is None:
            m = RTDETR(self._weights)
            self._local.model = m
        return m

    def __call__(self, frame: np.ndarray, conf: float = 0.35, verbose: bool = False):
        return self._model(frame, conf=conf, imgsz=self._imgsz, verbose=verbose)

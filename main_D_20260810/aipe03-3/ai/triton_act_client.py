"""Triton 版 ActionTransformer（AcT）client，把時序跌倒分類那顆搬上 Triton。

AcT 不是 ultralytics 模型、不回傳 `Results`，介面比原本的本地 torch 呼叫更單純：
輸入 30 幀 pose 特徵陣列（形狀 (30,34) 或 (1,30,34)），回傳原始 logits `np.ndarray (1,2)`
（index 0=跌倒、index 1=正常）。刻意回 logits 而非 (pred_class, conf)，讓 inference_test.py
下游原本的 `torch.softmax` / `torch.argmax` 邏輯幾乎一行都不用改，行為與本地 torch 對稱。

注意：tritonclient 的 HTTP client 底層用 gevent，greenlet 綁定「建立連線的執行緒」，
跨執行緒呼叫會 `greenlet.error: Cannot switch to a different thread`。inference_test.py
是每支相機一條 camera_worker 執行緒，所以 TritonRemoteModel 必須延遲到「呼叫它的那條
執行緒」內各自建立（thread-local 快取），不能在主執行緒 import 時建好共用。
（與 triton_detr_client.py / triton_pose_client.py 相同的 thread-local 建連模式。）
"""
import threading

import numpy as np
from ultralytics.utils.triton import TritonRemoteModel


class TritonActModel:
    """呼叫介面：`model(feats)` -> logits `np.ndarray (1, 2)`。

    `feats` 接受 (30, 34) 或 (1, 30, 34) 的 pose 特徵陣列，內部統一成 (1, 30, 34) float32。
    """

    def __init__(self, triton_url: str):
        self._triton_url = triton_url
        self._local = threading.local()  # 每執行緒各自持有一個 TritonRemoteModel

    @property
    def _trm(self) -> TritonRemoteModel:
        trm = getattr(self._local, "trm", None)
        if trm is None:
            trm = TritonRemoteModel(self._triton_url)  # 在「當前呼叫執行緒」內建立
            self._local.trm = trm
        return trm

    def __call__(self, feats: np.ndarray) -> np.ndarray:
        input_tensor = np.ascontiguousarray(feats, dtype=np.float32).reshape(1, 30, 34)
        # AcT 只有單一輸出 output (1, 2) logits。
        return self._trm(input_tensor)[0]

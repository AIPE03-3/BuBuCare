"""本地版 ActionTransformer（AcT）client —— `triton_act_client.TritonActModel` 的對照組。

存在的唯一理由是效能對照（見 ai/BENCHMARK_TRITON_VS_LOCAL.md）。生產路徑仍是 Triton 版。

介面與 `TritonActModel` 相同：`model(feats)` -> logits `np.ndarray (1, 2)`
（index 0=跌倒、1=正常）。刻意回 **logits 而非 (class, conf)**，與 Triton 版對稱，
讓 inference_test.py 下游的 `torch.softmax` / `torch.argmax` 一行都不用改。

⚠️ 權重 `ai/action_transformer.pth` 就是 `ai/triton_repo/action_transformer/1/model.onnx`
的來源（ai/export_models.py:173-213 匯出的），**兩邊同一顆模型**，所以這顆可以進主表。

⚠️ 下面的 `ActionTransformer` 結構必須與 `ai/inference_test.py:390-402` **逐字一致**
（那裡是唯一真相），否則 `load_state_dict` 會直接噴 key 不符。這裡重抄一份而不是
import inference_test，是因為它一被 import 就會去連 Triton / Kafka（模組層級就在建 client）
—— 與 ai/export_models.py:_build_action_transformer() 完全相同的理由與作法。
改那邊的結構時，這裡與 export_models.py 兩份都要跟著改。
"""
import os
import threading

import numpy as np
import torch
import torch.nn as nn

_AI_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_WEIGHTS = os.path.join(_AI_DIR, "action_transformer.pth")


class ActionTransformer(nn.Module):
    """與 ai/inference_test.py:390-402 逐字一致，見本檔 docstring 的警語。"""

    def __init__(self, input_dim=34, seq_len=30, num_classes=2):
        super(ActionTransformer, self).__init__()
        self.embedding = nn.Linear(input_dim, 64)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=64, nhead=4, dim_feedforward=128, batch_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=2)
        self.fc = nn.Sequential(
            nn.Linear(64, 32), nn.ReLU(), nn.Linear(32, num_classes)
        )

    def forward(self, x):
        x = self.embedding(x)
        x = self.transformer(x)
        return self.fc(x.mean(dim=1))


class LocalActModel:
    """呼叫介面比照 `TritonActModel`：`model(feats)` -> logits `np.ndarray (1, 2)`。

    `feats` 接受 (30, 34) 或 (1, 30, 34)，內部統一成 (1, 30, 34) float32。

    device 預設跟著 CUDA 可用性走。要強制比對 CPU 側可傳 `device="cpu"`，
    但本輪對照只比 GPU（見對照文件範圍說明）。

    thread-local 持有各自的 module 實例：理由同 local_pose_client，且 AcT 這顆只有
    315 KB，每執行緒各載一份的顯存成本可忽略。
    """

    def __init__(self, weights: str = DEFAULT_WEIGHTS, device: str | None = None):
        if not os.path.isfile(weights):
            raise FileNotFoundError(f"找不到 AcT 權重：{weights}")
        self._weights = weights
        self._device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._local = threading.local()

    @property
    def _model(self) -> ActionTransformer:
        m = getattr(self._local, "model", None)
        if m is None:
            m = ActionTransformer()
            m.load_state_dict(torch.load(self._weights, map_location="cpu"))
            m.to(self._device)
            m.eval()
            self._local.model = m
        return m

    def __call__(self, feats: np.ndarray) -> np.ndarray:
        x = np.ascontiguousarray(feats, dtype=np.float32).reshape(1, 30, 34)
        with torch.no_grad():
            out = self._model(torch.from_numpy(x).to(self._device))
        # 回 CPU 的 (1,2) ndarray，與 TritonActModel 的回傳型別一致。
        return out.detach().cpu().numpy()

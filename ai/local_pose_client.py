"""本地版 YOLO11-pose client —— `triton_pose_client.TritonPoseModel` 的對照組。

存在的唯一理由是**效能對照**：量「模型架在 Triton 上」與「模型直接載進這個 process」
差多少（見 ai/BENCHMARK_TRITON_VS_LOCAL.md）。生產路徑仍是 Triton 版，
本檔只在 `INFER_BACKEND=local` 時才會被建起來。

介面與 `TritonPoseModel` **逐字相同**：`model(frame, conf=..., verbose=...)` -> `[Results]`。
所以 inference_test.py 的呼叫端一行都不用改，只換建構的是哪個類別。

為什麼這支比 Triton 版短這麼多：Triton 版只能拿到 raw tensor (1,56,8400)，NMS 與
letterbox 反算全部得自己手寫；本地 `YOLO()` 原生就回標準 `Results`，前後處理是
ultralytics 內部做掉的。**這正是要量的差異之一** —— 兩邊的後處理實作不同（一邊手寫、
一邊官方），所以 client 端 wall time 的差距不能全歸給「網路來回」，詳見對照文件的
可信度邊界一節。

⚠️ 權重是 `ai/yolo11s-pose.pt`，也就是 `ai/triton_repo/yolo_pose/1/model.onnx` 的來源
（見 ai/export_models.py:132-150）。**兩邊同一顆模型**，這是主表能算單一變因的前提。
"""
import os
import threading

import numpy as np
from ultralytics import YOLO

_AI_DIR = os.path.dirname(os.path.abspath(__file__))
IMGSZ = 640
DEFAULT_WEIGHTS = os.path.join(_AI_DIR, "yolo11s-pose.pt")


class LocalPoseModel:
    """呼叫介面比照 `TritonPoseModel`：`model(frame, conf=..., verbose=...)` -> `[Results]`。

    thread-local 持有各自的 `YOLO` 實例。本地模型沒有 Triton 版那個
    gevent/greenlet 跨執行緒問題，但 inference_test.py 是每支相機一條 camera_worker
    執行緒，多執行緒共用同一個 torch module 做推論仍有狀態競爭風險
    （ultralytics predictor 會在物件上留 batch/results 狀態）。所以照 Triton 版的
    thread-local 模式做：每條執行緒第一次呼叫時才在該執行緒建自己的實例。

    代價是每條執行緒各載一份權重進顯存 —— 這是「不用 Triton」的真實成本之一，
    多路時顯存佔用會線性增加，對照文件要量的就是這個。
    """

    def __init__(self, weights: str = DEFAULT_WEIGHTS, imgsz: int = IMGSZ, iou: float = 0.7):
        if not os.path.isfile(weights):
            raise FileNotFoundError(f"找不到 pose 權重：{weights}")
        self._weights = weights
        self._imgsz = imgsz
        self._iou = iou
        self._local = threading.local()

    @property
    def _model(self) -> YOLO:
        m = getattr(self._local, "model", None)
        if m is None:
            m = YOLO(self._weights)
            self._local.model = m
        return m

    def __call__(self, frame: np.ndarray, conf: float = 0.45, verbose: bool = False):
        # iou 與 imgsz 明確傳入，對齊 TritonPoseModel 的 __init__ 預設（iou=0.7, imgsz=640），
        # 不吃 ultralytics 自己的預設值（iou=0.7 剛好相同，但寫明才不會被版本更動影響）。
        #
        # ⚠️ `rect=False` 是對照公平性的關鍵，不要拿掉。
        # ultralytics 預設 `rect=True`：1920×1080 會 letterbox 成 **640×384**（保比例、
        # 最小填充）；而 TritonPoseModel._preprocess 是寫死的 **640×640** 方形
        # （triton_pose_client.py:59 的 `LetterBox((640,640), auto=False)`），因為
        # Triton 那邊 config.pbtxt 的輸入雖是動態 H/W，client 一律送方形。
        #
        # 兩者餵給模型的**畫面解析度不同**（人在圖上的像素尺度不同），關鍵點座標會差到
        # 數十 px —— 2026-07-30 的 verify_backend_parity.py 就是這樣抓到的
        # （keypoint max diff 65.9 px，box 只差 2 px：同一個人、不同尺度）。
        # 那不是誰算錯，是兩條路的前處理不同；但若不對齊，效能對照就變成
        # 「640×640 vs 640×384」的比較（後者算的畫素少 40%，本地側會不公平地佔便宜）。
        # 設 rect=False 讓本地側也走 640×640 方形，變因才只剩「有沒有 Triton」。
        return self._model(frame, conf=conf, iou=self._iou, imgsz=self._imgsz,
                           rect=False, verbose=verbose)

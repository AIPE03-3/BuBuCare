"""Triton 版 YOLO11-pose client，介面模仿本地 `YOLO("yolo11s-pose.pt")` 呼叫方式。

背景：ultralytics 官方的 `YOLO(triton_url, task="pose")` 只保證 detect 任務能用，
pose 任務因為 client 端拿不到本地 .pt 內嵌的 kpt_shape/nc metadata 而會在
postprocess 階段報錯（見 ai/triton_verify_pose.py 的驗證紀錄）。

這裡改用 tritonclient 直接取 (1,56,8400) raw tensor，自己做 NMS + letterbox 反算後處理
（重用 ultralytics.utils.ops 裡已驗證過的函式，只有「56維怎麼切」是手寫，因為這是
YOLO11-pose 的固定已知輸出格式：4(box cxcywh) + 1(conf, nc=1 只有 person) + 17*3(keypoints)），
再包成標準 ultralytics.engine.results.Results 物件回傳 —— 這樣呼叫端（inference_test.py）
原本讀 `.keypoints.xyn` / `.boxes.conf` / `.boxes.xywh` / `.boxes.xyxy` / `.plot()` 的程式碼
完全不用改，行為與本地 `.pt` 呼叫一致。
"""
import threading

import numpy as np
import torch
from torchvision.ops import nms
from ultralytics.data.augment import LetterBox
from ultralytics.engine.results import Results
from ultralytics.utils.ops import scale_boxes, scale_coords
from ultralytics.utils.triton import TritonRemoteModel

IMGSZ = 640
NAMES = {0: "person"}


class TritonPoseModel:
    """呼叫介面比照 `ultralytics.YOLO`：`model(frame, conf=..., verbose=...)` -> `[Results]`。

    注意：tritonclient 的 HTTP client 底層用 gevent，greenlet 綁定「建立連線的執行緒」，
    跨執行緒呼叫會 `greenlet.error: Cannot switch to a different thread`。inference_test.py
    是每支相機一條 camera_worker 執行緒（見其 __main__），所以 TritonRemoteModel 不能在
    主執行緒（module import 時）建好共用，必須延遲到「呼叫它的那條執行緒」內各自建立。
    這裡用 thread-local 快取：每條執行緒第一次呼叫時，才在該執行緒建自己的連線。
    """

    def __init__(self, triton_url: str, imgsz: int = IMGSZ, iou: float = 0.7):
        self._triton_url = triton_url
        self._imgsz = imgsz
        self._iou = iou
        self._local = threading.local()  # 每執行緒各自持有一個 TritonRemoteModel

    @property
    def _trm(self) -> TritonRemoteModel:
        trm = getattr(self._local, "trm", None)
        if trm is None:
            trm = TritonRemoteModel(self._triton_url)  # 在「當前呼叫執行緒」內建立
            self._local.trm = trm
        return trm

    def __call__(self, frame: np.ndarray, conf: float = 0.45, verbose: bool = False):
        input_tensor = self._preprocess(frame)
        raw = self._trm(input_tensor)[0]  # (1, 56, 8400)
        result = self._postprocess(raw, frame, conf_thres=conf)
        return [result]

    def _preprocess(self, frame: np.ndarray) -> np.ndarray:
        lb = LetterBox((self._imgsz, self._imgsz), auto=False, stride=32)
        img = lb(image=frame)
        img = img[:, :, ::-1].transpose(2, 0, 1)  # BGR->RGB, HWC->CHW
        img = np.ascontiguousarray(img, dtype=np.float32) / 255.0
        return img[None]

    def _postprocess(self, raw: np.ndarray, frame: np.ndarray, conf_thres: float) -> Results:
        pred = torch.from_numpy(raw)[0].T  # (8400, 56)
        boxes_cxcywh, conf, kpts = pred[:, :4], pred[:, 4], pred[:, 5:]

        keep = conf > conf_thres
        boxes_cxcywh, conf, kpts = boxes_cxcywh[keep], conf[keep], kpts[keep]

        img1_shape = (self._imgsz, self._imgsz)
        img0_shape = frame.shape

        if len(conf) == 0:
            empty_boxes = torch.zeros((0, 6))
            empty_kpts = torch.zeros((0, 17, 3))
            return Results(frame, path="", names=NAMES, boxes=empty_boxes, keypoints=empty_kpts)

        cx, cy, w, h = boxes_cxcywh.unbind(-1)
        boxes_xyxy = torch.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], dim=-1)

        keep_idx = nms(boxes_xyxy, conf, self._iou)
        boxes_xyxy, conf, kpts = boxes_xyxy[keep_idx], conf[keep_idx], kpts[keep_idx]

        # letterbox 反算回原圖座標，重用 ultralytics 官方函式，不自己重算 pad/ratio。
        # scale_coords 用 coords[..., 0]/[..., 1] broadcast，最後一維必須是 2，不能攤平成 (N,34)。
        boxes_xyxy = scale_boxes(img1_shape, boxes_xyxy, img0_shape)
        kpts_view = kpts.view(-1, 17, 3)
        kpts_xy = scale_coords(img1_shape, kpts_view[:, :, :2].clone(), img0_shape)
        kpts_full = torch.cat([kpts_xy, kpts_view[:, :, 2:3]], dim=-1)  # 補回 visibility

        cls = torch.zeros((len(conf), 1))  # nc=1，只有 person
        boxes_data = torch.cat([boxes_xyxy, conf.unsqueeze(-1), cls], dim=-1)  # (N,6)

        return Results(frame, path="", names=NAMES, boxes=boxes_data, keypoints=kpts_full)

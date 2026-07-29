"""Triton 版 RT-DETR client，介面模仿本地 `RTDETR("rtdetr-l.pt")` 呼叫方式。

把環境物件偵測那顆搬上 Triton，包成與本地
`YOLO()`/`RTDETR()` 呼叫介面完全相同的 wrapper、回傳標準 ultralytics `Results`
物件，讓下游（inference_test.py / modules/chair_slip.py）讀 `.boxes`/`.names` 的
程式碼一行都不用改，只換模型來源。

RT-DETR 的後處理比 YOLO-seg 簡單很多（無 NMS、無 proto/mask）：
  - output0: (1, 300, 6) = 每筆 [cx, cy, w, h, score, class]，box 為「正規化 [0,1]」。
後處理完全對齊官方 `ultralytics.models.rtdetr.predict.RTDETRPredictor.postprocess`：
  split((4,1,1)) -> xywh2xyxy -> conf 過濾 -> box 直接乘原圖 W/H。
RT-DETR 官方前處理是「純 resize 到 640×640」（非保比例 letterbox），所以座標反算
只需乘原圖尺寸，不需算 pad/ratio。

注意：`.names` 為完整 80 類 COCO dict（下游靠 names[cls_id] 查 bed/chair/couch 等物件名）。
實際 export 走 `rtdetr-l.pt`（標準 COCO 80），故此處也從該權重讀 names。

⚠️ **2026-07-29 起 Triton 上 serving 的 `rt_detr` 是重訓版（v2），只有 5 類**
（person/chair/sofa/bed/tv，見 `ai/data.yaml`），**與這裡的 COCO 80 類 names 對不上** ——
`names[cls_id]` 查出來的名字會是錯的（例：v2 的 cls_id=4 是 tv，這裡會查成 COCO 的 airplane）。

現在**不會壞**，因為唯一的下游 `ai/inference_test.py:714-728` 算出 `detected_objects` /
`bed_box_xyxy` 之後全檔沒有任何地方讀（原讀取者 bed_exit / chair_slip 已於 2026-07-27 刪除），
所以類別名對不對完全沒有影響。留這段註解是為了下一個人：**要把那兩個值接回使用之前，
先把這裡的 names 改成跟當下 serving 的版本一致**（`ai/triton_repo/README.md` 有版本沿革），
不要假設它是 COCO。
"""
import threading

import cv2
import numpy as np
import torch
from ultralytics import RTDETR
from ultralytics.engine.results import Results
from ultralytics.utils import ops
from ultralytics.utils.triton import TritonRemoteModel

IMGSZ = 640
MAX_DET = 300  # RT-DETR decoder 固定 300 queries
# 從本地權重讀一次完整 80 類 names（下游 yolo_env_model.names[cls_id] 需要）。
# 只讀 metadata、不做推論，載入成本可忽略。
NAMES = RTDETR("rtdetr-l.pt").names


class TritonDetrModel:
    """呼叫介面比照 `ultralytics.RTDETR`：`model(frame, conf=..., verbose=...)` -> `[Results]`。

    另提供 `.names` 屬性（完整 80 類 dict），與本地 `RTDETR().names` 一致，
    讓下游 `yolo_env_model.names[cls_id]` 直接可用。

    注意：tritonclient 的 HTTP client 底層用 gevent，greenlet 綁定「建立連線的執行緒」，
    跨執行緒呼叫會 `greenlet.error: Cannot switch to a different thread`。inference_test.py
    是每支相機一條 camera_worker 執行緒，所以 TritonRemoteModel 必須延遲到「呼叫它的那條
    執行緒」內各自建立（thread-local 快取），不能在主執行緒 import 時建好共用。
    """

    def __init__(self, triton_url: str, imgsz: int = IMGSZ):
        self._triton_url = triton_url
        self._imgsz = imgsz
        self.names = NAMES
        self._local = threading.local()  # 每執行緒各自持有一個 TritonRemoteModel

    @property
    def _trm(self) -> TritonRemoteModel:
        trm = getattr(self._local, "trm", None)
        if trm is None:
            trm = TritonRemoteModel(self._triton_url)  # 在「當前呼叫執行緒」內建立
            self._local.trm = trm
        return trm

    def __call__(self, frame: np.ndarray, conf: float = 0.35, verbose: bool = False):
        input_tensor = self._preprocess(frame)
        # RT-DETR 只有單一輸出 output0 (1, 300, 6)。
        output0 = self._trm(input_tensor)[0]
        result = self._postprocess(output0, frame, conf_thres=conf)
        return [result]

    def _preprocess(self, frame: np.ndarray) -> np.ndarray:
        """RT-DETR 官方前處理：純 resize 到 640×640（非保比例 letterbox）。

        因為輸出座標是正規化 [0,1]，反算時直接乘原圖 W/H 即可，故前處理不需保比例。
        """
        img = cv2.resize(frame, (self._imgsz, self._imgsz))
        img = img[:, :, ::-1].transpose(2, 0, 1)  # BGR->RGB, HWC->CHW
        img = np.ascontiguousarray(img, dtype=np.float32) / 255.0
        return img[None]  # (1, 3, 640, 640)

    def _postprocess(self, output0: np.ndarray, frame: np.ndarray, conf_thres: float) -> Results:
        # 對齊官方 RTDETRPredictor.postprocess：output0 為 (300, 6) = [cx,cy,w,h,score,cls]，
        # box 正規化 [0,1]。
        preds = torch.from_numpy(output0)  # (300, 6)
        bboxes, scores, labels = preds.split((4, 1, 1), dim=-1)
        bboxes = ops.xywh2xyxy(bboxes)  # 正規化座標系的 cxcywh -> x1y1x2y2
        idx = scores.squeeze(-1) > conf_thres
        pred = torch.cat([bboxes, scores, labels], dim=-1)[idx][:MAX_DET]

        if pred.shape[0] == 0:
            return Results(frame, path="", names=self.names, boxes=torch.zeros((0, 6)), masks=None)

        h, w = frame.shape[:2]
        pred[..., [0, 2]] *= w  # 正規化 x -> 原圖寬
        pred[..., [1, 3]] *= h  # 正規化 y -> 原圖高

        # DETR 無 mask，回 masks=None；下游疊圖處已有 getattr(..., 'masks', None) guard。
        return Results(frame, path="", names=self.names, boxes=pred, masks=None)

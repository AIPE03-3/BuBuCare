# agent/nodes/ingest.py
"""ingest 節點：把 Kafka 1 的原始訊息變成可信的 AgentState。

純函式節點（副作用只有寫 DLQ log），做兩件事：
1. Pydantic 驗證訊息 —— 壞資料進 DLQ，不硬塞假值往下游送
2. 經 ImageStore 解析圖檔路徑 —— 只認識介面，不知道也不在乎圖從哪來

任何一步失敗都在 state["error"] 標記原因，由圖的條件邊短路到 END：
一筆壞訊息不該讓整個 consumer 掛掉。
"""
import logging

from pydantic import ValidationError

from agent.image_store import ImageNotFound, ImageStore
from agent.jsonl import append_jsonl
from agent.schemas import AgentState, AlertMessage

logger = logging.getLogger("agent.ingest")


def make_ingest_node(image_store: ImageStore, dlq_path: str):
    """依賴用參數注入而非 import 全域：測試要換 store 或 DLQ 路徑不必動環境變數。"""

    def ingest(state: AgentState) -> dict:
        raw = state.get("raw") or {}

        # 1. 驗證：camera_id 非數字之類的壞資料在這裡就被擋下
        try:
            alert = AlertMessage(**raw)
        except (ValidationError, TypeError) as e:
            return _reject(dlq_path, raw, "validation_failed", str(e))

        # 2. 取圖：取不到就跳過這筆（沿用現況「找不到照片就跳過」的行為）
        try:
            image_path = image_store.resolve(alert.image_filename or "")
        except ImageNotFound as e:
            return _reject(dlq_path, raw, "image_not_found", str(e))

        logger.info("受理告警 device=%s type=%s 圖檔=%s",
                    alert.camera_label, alert.event_type, image_path)
        return {
            "alert": alert,
            "image_path": image_path,
            "vlm_retries": 0,
            "judge_retries": 0,
            "error": None,
        }

    return ingest


def _reject(dlq_path: str, raw: dict, reason: str, detail: str) -> dict:
    # DLQ 記的是「原始訊息 + 為什麼不收」，事後要重放或修邊緣端都靠這份
    logger.warning("訊息進 DLQ（%s）：%s", reason, detail)
    append_jsonl(dlq_path, {"reason": reason, "detail": detail, "raw": raw})
    return {"error": f"{reason}: {detail}"}


def has_error(state: AgentState) -> bool:
    return bool(state.get("error"))

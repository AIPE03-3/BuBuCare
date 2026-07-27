# agent/nodes/publish.py
"""publish 節點：組 Kafka 2 訊息並送出。

三個不可退讓的點：
1. **輸出是現有格式的超集**——舊欄位一個不動，backend/kafka_consumer.py 不改也能跑。
2. **uncertain 一律降級成 ai_verdict=null**，絕不對外送出 uncertain，也絕不自動判誤報。
3. **shadow 模式只寫檔不送 Kafka**——cutover 前要能與 vlm_worker 併行驗證。

純函式（build_report / dedupe_key）與副作用（送 Kafka、寫檔）刻意分開，
組訊息的邏輯不必連 Kafka 就能單測。
"""
import logging

from agent.jsonl import append_jsonl
from agent.schemas import AgentState, AlertMessage, ProcessedReport

logger = logging.getLogger("agent.publish")

# 對外只承認這兩個 verdict；uncertain 與任何異常都變成 None（交回人工）
PUBLISHABLE_VERDICTS = ("true_alarm", "false_alarm")


def to_ai_verdict(verdict: str | None) -> str | None:
    """Agent 內部的 verdict → 對外欄位。

    這是「安全非對稱」的最後一道轉換：判不出來就是 null，等同現況交回人工，
    而不是幫忙猜一個 false_alarm 把事件關掉。
    """
    return verdict if verdict in PUBLISHABLE_VERDICTS else None


def build_report(state: AgentState, received_at: str) -> ProcessedReport:
    """把 state 組成 Kafka 2 訊息。純函式，不碰任何外部資源。"""
    alert: AlertMessage = state["alert"]
    detected_at = alert.detected_at.isoformat() if alert.detected_at else received_at

    return ProcessedReport(
        # ── 既有欄位：語意與 vlm_worker 現況完全一致 ──
        device_id=alert.device_id,
        event_type=alert.event_type,
        clip_path=alert.clip_path or "/vids/fallback.mp4",
        detected_at=detected_at,
        snapshot_path=state["image_path"],
        yolo_score=alert.yolo_score,
        yolo_threshold=alert.yolo_threshold,
        vlm_summary=state.get("vlm_report") or "【系統警告】本次未取得影像判讀。",
        severity=state.get("severity", "low"),
        # ── 新增欄位 ──
        ai_verdict=to_ai_verdict(state.get("verdict")),
        ai_confidence=state.get("confidence"),
        ai_reasoning=state.get("reasoning"),
    )


def dedupe_key(report: ProcessedReport) -> str:
    """冪等鍵：Kafka 重複消費時，同一起事件不該在 DB 產生兩筆。"""
    return f"{report.device_id}|{report.detected_at}|{report.event_type}"


class SeenKeys:
    """記住最近送過的冪等鍵，上限之內先進先出。

    刻意只做「行程內記憶」而非持久化：重複消費幾乎都發生在同一個 consumer 的
    重啟或 rebalance 窗口內，行程內去重就擋掉絕大多數；為此開一張 DB 表
    是把簡單問題複雜化。真的要跨行程去重，該做的是後端建檔時的唯一索引。
    """

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._keys: dict[str, None] = {}

    def seen(self, key: str) -> bool:
        if key in self._keys:
            return True
        self._keys[key] = None
        if len(self._keys) > self.max_size:
            self._keys.pop(next(iter(self._keys)))
        return False


def make_publish_node(producer, topic: str, *, shadow: bool, shadow_log_path: str,
                      seen: SeenKeys | None = None, now_fn=None):
    """producer 在 shadow 模式下可以是 None——那條路徑本來就不該碰 Kafka。"""
    from datetime import datetime

    seen = seen if seen is not None else SeenKeys()
    now_fn = now_fn or (lambda: datetime.now().isoformat(timespec="seconds"))

    def publish(state: AgentState) -> dict:
        report = build_report(state, received_at=now_fn())
        key = dedupe_key(report)

        if seen.seen(key):
            logger.info("重複事件，略過發布：%s", key)
            return {"published": False, "skipped_reason": "duplicate"}

        payload = report.model_dump()

        if shadow:
            # Shadow：判定完整落地供比對，但一則都不送 Kafka 2
            append_jsonl(shadow_log_path, {"dedupe_key": key, "report": payload})
            logger.info("[SHADOW] 判定已記錄，未送 Kafka：%s ai_verdict=%s",
                        key, report.ai_verdict)
            return {"published": False, "skipped_reason": "shadow"}

        producer.send(topic, value=payload)
        producer.flush()
        logger.info("已送出 Kafka 2：%s ai_verdict=%s severity=%s",
                    key, report.ai_verdict, report.severity)
        return {"published": True}

    return publish

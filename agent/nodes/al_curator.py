# agent/nodes/al_curator.py
"""al_curator 節點：判斷這張快照值不值得收進回訓資料集。

取代 ai/vlm_worker.py:136 的寫死規則 `0.35 <= yolo_score <= 0.85`。
那條規則只看分數，看不出「分數 0.9 但其實是誤報」這種真正有價值的樣本，
也會收一堆「分數 0.5 且模型判得對」的無用樣本。改由 LLM 綜合判定結果來挑。

三個不可退讓的點：
1. **收樣本失敗不得影響主流程**——事件該送還是要送，資料集是附加價值。
2. **curator 失效時退回既有規則**，維持現況行為，不是整個停收。
3. **巡檢事件不收**（沿用現況：只有告警類事件才進主動學習）。
"""
import logging

from agent.prompts import build_al_curator_prompt
from agent.schemas import AgentState, ALDecision

logger = logging.getLogger("agent.al_curator")


def fallback_decision(yolo_score: float, min_score: float, max_score: float) -> ALDecision:
    """curator 用不了時的退路：沿用 vlm_worker 的寫死區間。

    保留它不是因為這規則好，而是因為「LLM 掛掉就完全停止收樣本」比「收得粗糙」更糟——
    資料集斷流是不可逆的，那段時間的樣本永遠補不回來。
    """
    keep = min_score <= yolo_score <= max_score
    return ALDecision(
        keep=keep,
        reason=f"策展判斷不可用，退回既有規則（{min_score}–{max_score} 區間收錄），"
               f"本次 yolo_score={yolo_score:.2f}",
        priority="low",
    )


def make_al_curator_node(model, store, *, enabled: bool, fallback_min: float, fallback_max: float):
    """model 吐 ALDecision；store 負責落地。兩者都可注入假的替身。"""

    def al_curator(state: AgentState) -> dict:
        if not enabled:
            return {"al_decision": None}

        alert = state["alert"]
        # 巡檢事件不是告警，收進跌倒訓練集沒有意義（沿用現況行為）
        if alert.is_routine_check:
            return {"al_decision": None}

        decision = _decide(model, state, alert, fallback_min, fallback_max)

        if decision.keep:
            store.save(state["image_path"], {
                "event_type": alert.event_type,
                "camera_id": alert.camera_label,
                "device_id": alert.device_id,
                "yolo_score": alert.yolo_score,
                "yolo_threshold": alert.yolo_threshold,
                "agent_verdict": state.get("verdict"),
                "agent_confidence": state.get("confidence"),
                "keep_reason": decision.reason,
                "priority": decision.priority,
            })
        else:
            logger.debug("不收錄樣本：%s", decision.reason)

        return {"al_decision": decision}

    return al_curator


def _decide(model, state, alert, fallback_min: float, fallback_max: float) -> ALDecision:
    try:
        decision = model.invoke(build_al_curator_prompt(alert, state))
    except Exception as e:
        logger.warning("策展判斷失敗，退回既有規則：%s", e)
        return fallback_decision(alert.yolo_score, fallback_min, fallback_max)

    if not isinstance(decision, ALDecision):
        logger.warning("策展判斷回傳型別非預期：%r", type(decision))
        return fallback_decision(alert.yolo_score, fallback_min, fallback_max)

    return decision


def build_al_curator(settings, llm_factory, store_factory):
    """組裝用：把設定攤開成節點需要的參數，讓 graph.py 保持乾淨。"""
    return make_al_curator_node(
        llm_factory(),
        store_factory(),
        enabled=settings.al_enabled,
        fallback_min=settings.al_fallback_min_score,
        fallback_max=settings.al_fallback_max_score,
    )

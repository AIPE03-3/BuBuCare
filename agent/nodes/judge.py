# agent/nodes/judge.py
"""judge 節點：綜合 yolo_score、VLM 報告、事件類型，做出複判。

這是整個 Agent 唯一「下判斷」的地方，也是安全策略的落點：

- 地端小模型的 structured output 不穩，**解析失敗是預期中的常態**。
  失敗一律降級為 uncertain（publish 會轉成 ai_verdict=null，交回人工），
  這是必要防線，不是加分項（見 agent/docs/01-architecture.md §4）。
- 寧可不判也不誤判：任何異常路徑都不會產出 false_alarm。
"""
import logging

from agent.prompts import build_judge_prompt
from agent.schemas import AgentState, JudgeResult

logger = logging.getLogger("agent.judge")


def degraded_result(reason: str) -> dict:
    """判不出來時的統一產出：uncertain + 零信心 + 說清楚為什麼。

    注意 verdict 不是 false_alarm——Agent 沒有「因為壞掉所以關掉事件」的權力。
    """
    return {
        "verdict": "uncertain",
        "confidence": 0.0,
        "reasoning": f"AI 無法判定，請人工複判。原因：{reason}",
    }


def make_judge_node(model, max_retries: int):
    """model 是 with_structured_output(JudgeResult) 之後的模型；測試注入假的。"""

    def judge(state: AgentState) -> dict:
        alert = state["alert"]
        vlm_report = state.get("vlm_report")

        # VLM 重試耗盡：沒有影像證據就沒有判定的基礎，不要叫 LLM 硬掰
        if not vlm_report:
            return degraded_result("VLM 影像判讀失敗，重試已耗盡")

        try:
            result = model.invoke(build_judge_prompt(alert, vlm_report))
        except Exception as e:
            # 地端模型吐不出合法 JSON 是常態，接住降級即可，不讓例外中斷 consumer
            logger.warning("judge 解析失敗，降級交回人工：%s", e)
            return degraded_result(f"判定結果解析失敗（{type(e).__name__}）")

        if not isinstance(result, JudgeResult):
            logger.warning("judge 回傳型別非預期：%r", type(result))
            return degraded_result("判定結果格式不符")

        logger.info("judge 判定 %s（信心 %.2f）", result.verdict, result.confidence)
        return {
            "verdict": result.verdict,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
        }

    return judge


def route_after_judge(state: AgentState) -> str:
    """judge 之後的條件邊：uncertain 且還有補問次數 → 回頭再問 VLM 一次，否則發布。

    純函式，圖的分支邏輯可以直接單測，不必真的跑整張圖。
    """
    if state.get("verdict") != "uncertain":
        return "publish"
    # VLM 都失敗了就別再問了，再問一次也只會再失敗一次
    if not state.get("vlm_report"):
        return "publish"
    if state.get("judge_retries", 0) >= _max_retries_of(state):
        return "publish"
    return "retry_vlm"


def _max_retries_of(state: AgentState) -> int:
    # 上限由組圖時綁進 state（graph.py 設定），避免這支純函式去讀全域設定
    return state.get("judge_max_retries", 0)


def make_followup_node():
    """判 uncertain 要回頭補問前，設定追問內容並記一次重試。"""
    from agent.prompts import VLM_FOLLOWUP_SUFFIX

    def prepare_followup(state: AgentState) -> dict:
        return {
            "followup": VLM_FOLLOWUP_SUFFIX,
            "judge_retries": state.get("judge_retries", 0) + 1,
        }

    return prepare_followup

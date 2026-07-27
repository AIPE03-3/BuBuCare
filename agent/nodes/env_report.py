# agent/nodes/env_report.py
"""env_report 節點：定時環境巡檢的分流路徑。

沿用現況功能，不加戲：巡檢事件用專屬 prompt 請 VLM 產出環境報告，
不做 true_alarm / false_alarm 複判——巡檢本來就不是告警，沒有東西要判。

因此這條路徑的產出固定是 verdict=uncertain（→ 對外 ai_verdict=null）、severity=low，
與現況 vlm_worker 對巡檢訊息的行為一致。
"""
import logging

from agent.nodes.vlm import analyze_with_retry
from agent.prompts import build_vlm_routine_prompt
from agent.schemas import AgentState

logger = logging.getLogger("agent.env_report")


def make_env_report_node(client, max_retries: int):
    def env_report(state: AgentState) -> dict:
        alert = state["alert"]
        prompt = build_vlm_routine_prompt(alert)
        report, error = analyze_with_retry(client, state["image_path"], prompt, max_retries)

        if report is None:
            logger.error("巡檢報告產生失敗：%s", error)
            report = f"【系統警告】環境巡檢中斷。相機: {alert.camera_label}，原因: {error}"

        logger.info("巡檢報告完成 camera=%s", alert.camera_label)
        return {
            "vlm_report": report,
            # 巡檢不做複判：verdict 保持 uncertain，publish 會轉成 ai_verdict=null
            "verdict": "uncertain",
            "confidence": 0.0,
            "reasoning": "定時環境巡檢，非告警事件，不做真假判定。",
            "severity": "low",
        }

    return env_report

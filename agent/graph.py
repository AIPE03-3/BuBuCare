# agent/graph.py
"""LangGraph 圖組裝（見 agent/docs/01-architecture.md §3.2）。

    ingest ─┬─(壞資料)────────────────────→ END
            ├─(巡檢事件)──→ env_report ──────────────────┐
            └─(告警事件)──→ vlm_analyze → judge ─┬─(uncertain 且還有補問次數)
                                 ↑                │      → followup → 回 vlm_analyze
                                 └────────────────┘                          │
                                                  └─(其餘)─────────────────────┴→ publish
                                                                                    ↓
                                                                            al_curator → END
                                                                          （告警已送出，不擋通知）

所有依賴（image store、VLM client、judge 模型、Kafka producer）都從外面傳進來，
build_graph 自己不去讀環境變數也不建任何連線——這樣測試才能把整張圖跑在假的替身上。
"""
import logging

from langgraph.graph import END, START, StateGraph

from agent.nodes.al_curator import make_al_curator_node
from agent.nodes.env_report import make_env_report_node
from agent.nodes.ingest import has_error, make_ingest_node
from agent.nodes.judge import make_followup_node, make_judge_node, route_after_judge
from agent.nodes.publish import make_publish_node
from agent.nodes.vlm import make_vlm_node
from agent.schemas import AgentState

logger = logging.getLogger("agent.graph")


def route_after_ingest(state: AgentState) -> str:
    """ingest 之後的分流：壞資料直接結束，巡檢與告警走不同路徑。"""
    if has_error(state):
        return "drop"
    return "routine" if state["alert"].is_routine_check else "review"


def build_graph(*, image_store, vlm_client, judge_model, curator_model, sample_store,
                producer, settings):
    graph = StateGraph(AgentState)

    graph.add_node("ingest", make_ingest_node(image_store, settings.dlq_log_path))
    graph.add_node("vlm_analyze", make_vlm_node(vlm_client, settings.vlm_max_retries))
    graph.add_node("judge", make_judge_node(judge_model, settings.judge_max_retries))
    graph.add_node("followup", make_followup_node())
    graph.add_node("env_report", make_env_report_node(vlm_client, settings.vlm_max_retries))
    graph.add_node("al_curator", make_al_curator_node(
        curator_model,
        sample_store,
        enabled=settings.al_enabled,
        fallback_min=settings.al_fallback_min_score,
        fallback_max=settings.al_fallback_max_score,
    ))
    graph.add_node("publish", make_publish_node(
        producer,
        settings.kafka_out_topic,
        shadow=settings.shadow_mode,
        shadow_log_path=settings.shadow_log_path,
    ))

    graph.add_edge(START, "ingest")
    graph.add_conditional_edges(
        "ingest",
        route_after_ingest,
        {"drop": END, "routine": "env_report", "review": "vlm_analyze"},
    )
    graph.add_edge("vlm_analyze", "judge")
    graph.add_conditional_edges(
        "judge",
        route_after_judge,
        {"publish": "publish", "retry_vlm": "followup"},
    )
    graph.add_edge("followup", "vlm_analyze")   # 帶著追問回頭再問一次 VLM
    graph.add_edge("env_report", "publish")
    # 策展刻意排在 publish **之後**：它多花約 3 秒的 LLM 呼叫，
    # 而產出（al_decision）沒有任何人讀，publish 也用不到——
    # 排在前面等於讓跌倒通知白等一個資料集決定。告警先送出去，樣本慢慢挑。
    graph.add_edge("publish", "al_curator")
    graph.add_edge("al_curator", END)

    return graph.compile()


def run_once(compiled_graph, raw_message: dict, judge_max_retries: int) -> dict:
    """跑一筆訊息。judge_max_retries 綁進初始 state，讓分支純函式不必讀全域設定。"""
    return compiled_graph.invoke({"raw": raw_message, "judge_max_retries": judge_max_retries})

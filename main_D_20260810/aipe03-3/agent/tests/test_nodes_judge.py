# agent/tests/test_nodes_judge.py
# 驗收重點（WBS P1.3）：fake LLM 下四種 verdict 路徑皆可走通；
# uncertain 重試耗盡 → ai_verdict=null（降級路徑是必要防線，必測）。

import pytest

from agent.nodes.judge import (
    degraded_result,
    make_followup_node,
    make_judge_node,
    route_after_judge,
)
from agent.schemas import AlertMessage, JudgeResult

ALERT = AlertMessage(event_type="Fall_Detected", camera_id="101", yolo_score=0.72)
BASE_STATE = {"alert": ALERT, "image_path": "/img.jpg", "vlm_report": "長者倒臥於地面"}


def result(verdict, confidence=0.9):
    return JudgeResult(verdict=verdict, confidence=confidence, reasoning="理由")


# ── 四種 verdict 路徑 ───────────────────────────────────
def test_判真警報(fake_structured_llm):
    node = make_judge_node(fake_structured_llm([result("true_alarm")]), max_retries=1)

    out = node(BASE_STATE)

    assert out["verdict"] == "true_alarm"
    assert out["confidence"] == 0.9


def test_判誤報(fake_structured_llm):
    model = fake_structured_llm([result("false_alarm", confidence=0.8)])

    out = make_judge_node(model, max_retries=1)(BASE_STATE)

    assert out["verdict"] == "false_alarm"


def test_判不確定(fake_structured_llm):
    model = fake_structured_llm([result("uncertain", confidence=0.3)])

    out = make_judge_node(model, max_retries=1)(BASE_STATE)

    assert out["verdict"] == "uncertain"


def test_解析失敗降級為_uncertain(fake_structured_llm):
    # 地端小模型吐不出合法 JSON 是常態，必須接住而不是讓例外中斷 consumer
    model = fake_structured_llm([ValueError("無法解析 JSON")])

    out = make_judge_node(model, max_retries=1)(BASE_STATE)

    assert out["verdict"] == "uncertain"
    assert out["confidence"] == 0.0
    assert "請人工複判" in out["reasoning"]


def test_模型回傳型別不符也降級(fake_structured_llm):
    model = fake_structured_llm([{"verdict": "true_alarm"}])   # 回 dict 而非 JudgeResult

    out = make_judge_node(model, max_retries=1)(BASE_STATE)

    assert out["verdict"] == "uncertain"


# ── 安全非對稱：異常路徑絕不產出 false_alarm ──────────────
def test_VLM_失敗時不呼叫模型直接降級(fake_structured_llm):
    # 沒有影像證據就沒有判定基礎，不該叫 LLM 硬掰
    model = fake_structured_llm([])   # 一被呼叫就會 AssertionError
    node = make_judge_node(model, max_retries=1)

    out = node({**BASE_STATE, "vlm_report": None})

    assert out["verdict"] == "uncertain"
    assert model.calls == []


@pytest.mark.parametrize("broken_state", [
    {"vlm_report": None},
    {"vlm_report": ""},
])
def test_任何異常路徑都不會判成誤報(fake_structured_llm, broken_state):
    # 架構層防死：Agent 不得因為自己壞掉而把事件關成誤報
    out = make_judge_node(fake_structured_llm([]), max_retries=1)({**BASE_STATE, **broken_state})

    assert out["verdict"] != "false_alarm"


def test_降級產出只有三個欄位且不含後端已移除的欄位():
    # severity 已隨後端 2026-07-19（1bbb585）移除，降級路徑不再需要 legacy_severity 退路
    out = degraded_result("x")

    assert set(out) == {"verdict", "confidence", "reasoning"}
    assert out["verdict"] == "uncertain"


# ── 補問迴圈的分支 ──────────────────────────────────────
def test_確定的判定直接發布():
    for verdict in ("true_alarm", "false_alarm"):
        state = {"verdict": verdict, "vlm_report": "報告", "judge_retries": 0, "judge_max_retries": 1}
        assert route_after_judge(state) == "publish"


def test_不確定且還有補問次數就回頭問_VLM():
    state = {"verdict": "uncertain", "vlm_report": "報告", "judge_retries": 0, "judge_max_retries": 1}

    assert route_after_judge(state) == "retry_vlm"


def test_不確定但補問次數耗盡就發布():
    state = {"verdict": "uncertain", "vlm_report": "報告", "judge_retries": 1, "judge_max_retries": 1}

    assert route_after_judge(state) == "publish"


def test_VLM_本來就失敗時不再補問():
    # 再問一次也只會再失敗一次，白白多花一輪
    state = {"verdict": "uncertain", "vlm_report": None, "judge_retries": 0, "judge_max_retries": 1}

    assert route_after_judge(state) == "publish"


def test_未設補問上限時預設不補問():
    state = {"verdict": "uncertain", "vlm_report": "報告", "judge_retries": 0}

    assert route_after_judge(state) == "publish"


def test_補問節點設定追問內容並累加次數():
    out = make_followup_node()({"judge_retries": 0})

    assert "【補充追問】" in out["followup"]
    assert out["judge_retries"] == 1

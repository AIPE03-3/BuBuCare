# agent/tests/test_nodes_al_curator.py
# 驗收重點（WBS P4.1）：輸出 {keep, reason, priority}；取代 0.35–0.85 寫死規則；
# 打包沿用既有目錄格式。

import pytest

from agent.nodes.al_curator import fallback_decision, make_al_curator_node
from agent.schemas import AlertMessage, ALDecision

ALERT = AlertMessage(event_type="Fall_Detected", camera_id="101",
                     image_filename="a.jpg", yolo_score=0.41)
STATE = {
    "alert": ALERT,
    "image_path": "/imgs/a.jpg",
    "vlm_report": "長者倒臥於地面",
    "verdict": "true_alarm",
    "confidence": 0.88,
    "reasoning": "姿態與跌倒相符",
}


class FakeStore:
    def __init__(self):
        self.saved = []

    def save(self, image_path, metadata):
        self.saved.append((image_path, metadata))
        return image_path


class FakeCurator:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def invoke(self, prompt, *args, **kwargs):
        self.calls.append(prompt)
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def build(results, *, enabled=True, store=None):
    store = store or FakeStore()
    node = make_al_curator_node(FakeCurator(results), store,
                                enabled=enabled, fallback_min=0.35, fallback_max=0.85)
    return node, store


# ── 收錄決定 ────────────────────────────────────────────
def test_決定收錄時樣本落地():
    decision = ALDecision(keep=True, reason="YOLO 僅 0.41 但確認跌倒，屬漏抓盲點", priority="high")
    node, store = build([decision])

    out = node(STATE)

    assert out["al_decision"].keep is True
    assert len(store.saved) == 1


def test_決定不收錄時不落地():
    node, store = build([ALDecision(keep=False, reason="模型已經判得很準", priority="low")])

    node(STATE)

    assert store.saved == []


def test_sidecar_帶齊理由與判定脈絡():
    decision = ALDecision(keep=True, reason="漏抓盲點", priority="high")
    node, store = build([decision])

    node(STATE)

    _, metadata = store.saved[0]
    assert metadata["keep_reason"] == "漏抓盲點"
    assert metadata["priority"] == "high"
    assert metadata["yolo_score"] == 0.41
    assert metadata["agent_verdict"] == "true_alarm"
    assert metadata["agent_confidence"] == 0.88


# ── 取代寫死規則 ────────────────────────────────────────
def test_高分誤報也可能被收錄():
    # 這正是 0.35–0.85 寫死規則抓不到的：分數 0.92 但其實是誤報，是很有價值的盲點
    high_score = ALERT.model_copy(update={"yolo_score": 0.92})
    node, store = build([ALDecision(keep=True, reason="高分誤觸發，屬誤報盲點", priority="high")])

    out = node({**STATE, "alert": high_score, "verdict": "false_alarm"})

    assert out["al_decision"].keep is True
    assert len(store.saved) == 1


def test_區間內但模型判得準也可能不收():
    # 反向：0.5 落在舊規則區間內會被無條件收錄，但模型判得準的樣本收了是浪費
    mid = ALERT.model_copy(update={"yolo_score": 0.5})
    node, store = build([ALDecision(keep=False, reason="模型已經會了", priority="low")])

    node({**STATE, "alert": mid})

    assert store.saved == []


# ── 降級：curator 失效退回既有規則 ───────────────────────
@pytest.mark.parametrize("score,expected_keep", [
    (0.20, False),   # 區間外
    (0.35, True),    # 下界含
    (0.60, True),
    (0.85, True),    # 上界含
    (0.95, False),
])
def test_退路規則沿用既有區間(score, expected_keep):
    assert fallback_decision(score, 0.35, 0.85).keep is expected_keep


def test_LLM_失敗時退回既有規則而非停收():
    # 資料集斷流是不可逆的：那段時間的樣本永遠補不回來，所以不能整個停收
    node, store = build([RuntimeError("模型連不上")])

    out = node(STATE)   # yolo_score=0.41，落在退路區間內

    assert out["al_decision"].keep is True
    assert "退回既有規則" in out["al_decision"].reason
    assert len(store.saved) == 1


def test_回傳型別不符也退回既有規則():
    node, store = build([{"keep": True}])

    out = node(STATE)

    assert "退回既有規則" in out["al_decision"].reason


def test_收樣本失敗不影響主流程():
    class BrokenStore:
        def save(self, image_path, metadata):
            return None      # sample_store 自己吞掉例外後回 None

    node, _ = build([ALDecision(keep=True, reason="x", priority="high")], store=BrokenStore())

    assert node(STATE)["al_decision"].keep is True   # 沒有丟例外


# ── 開關與分流 ──────────────────────────────────────────
def test_關閉時完全不動作():
    node, store = build([], enabled=False)

    assert node(STATE)["al_decision"] is None
    assert store.saved == []


def test_巡檢事件不收錄():
    # 巡檢不是告警，收進跌倒訓練集沒有意義（沿用現況行為）
    routine = AlertMessage(event_type="Routine_Environment_Sanity_Check",
                           camera_id="101", image_filename="a.jpg", yolo_score=0.5)
    node, store = build([])

    assert node({**STATE, "alert": routine})["al_decision"] is None
    assert store.saved == []

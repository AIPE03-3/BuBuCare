# agent/tests/test_graph.py
# 驗收重點（WBS P1.4/P1.5）：端到端餵一筆 Kafka 1 測試訊息 → Kafka 2 收到相容格式訊息；
# 巡檢訊息走巡檢路徑、不觸發複判。
#
# 整張圖跑在假的替身上：無網路、無 Kafka、無 Ollama。

import pytest

from agent.graph import build_graph, route_after_ingest, run_once
from agent.nodes.vlm import VlmError
from agent.schemas import AlertMessage, JudgeResult

# 這兩則訊息是從邊緣端「程式碼」抄的真實格式，不是文件範例——端到端測試若用理想化的
# 假訊息，就測不出「真實訊息會不會被 schema 拒絕」，而那正是最容易在 cutover 當天炸掉的地方。
# 來源：ai/inference_test.py:341（告警，無 camera_id）、ai/modules/sanity_check.py:35（巡檢）
ALERT_MESSAGE = {
    "device_id": 301,
    "event_type": "fall",
    "clip_path": "test_demo/test1.mp4",
    "detected_at": "2026-07-19T15:30:00",
    "snapshot_path": "/abs/path/snapshot_Room_301_Bed_20260719_153000.jpg",
    "image_filename": "snapshot_Room_301_Bed_20260719_153000.jpg",
    "yolo_score": 0.72,
    "yolo_threshold": 0.45,   # 慢車道保留：AI 內部欄位，judge prompt 比大小用
    "vlm_summary": "【AI 信心度不足】已觸發大模型二審…",
}
ROUTINE_MESSAGE = {
    "alert_id": "RTN_Room_301_Bed_1753000000",
    "device_id": 301,
    "event_type": "Routine_Environment_Sanity_Check",
    "detected_at": "2026-07-19T15:30:00",
    "camera_id": "Room_301_Bed",
    "yolo_score": 1.0,
    "image_filename": "snapshot_Room_301_Bed_20260719_153000.jpg",
    "severity": "low",
    "status": "PENDING_VLM_ROUTE",
}


class FakeStore:
    def __init__(self, error=None):
        self.error = error

    def resolve(self, image_filename):
        if self.error:
            raise self.error
        return f"/imgs/{image_filename}"


class ScriptedVlm:
    def __init__(self, script):
        self.script = list(script)
        self.prompts = []

    def analyze(self, image_path, prompt):
        self.prompts.append(prompt)
        item = self.script.pop(0) if self.script else "預設報告"
        if isinstance(item, Exception):
            raise item
        return item


class FakeSampleStore:
    def __init__(self):
        self.saved = []

    def save(self, image_path, metadata):
        self.saved.append((image_path, metadata))
        return image_path


class ScriptedJudge:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def invoke(self, prompt, *args, **kwargs):
        self.calls += 1
        item = self.script.pop(0) if self.script else JudgeResult(
            verdict="uncertain", confidence=0.0, reasoning="腳本用盡"
        )
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def build(settings, fake_producer):
    """組一張跑在假替身上的圖；回傳 (跑一筆的函式, producer, vlm, judge)。"""
    def _build(vlm_script=("VLM 報告：長者倒臥於床邊地面",),
               judge_script=(JudgeResult(verdict="true_alarm", confidence=0.9,
                                         reasoning="姿態與跌倒相符"),),
               store=None, **setting_overrides):
        import dataclasses
        cfg = dataclasses.replace(settings, **setting_overrides) if setting_overrides else settings
        vlm = ScriptedVlm(vlm_script)
        judge = ScriptedJudge(judge_script)
        graph = build_graph(
            image_store=store or FakeStore(),
            vlm_client=vlm,
            judge_model=judge,
            # 策展預設關閉：這批測試在乎的是複判與發布，開著會讓每個案例都多一次假 LLM 呼叫
            curator_model=ScriptedJudge([]),
            sample_store=FakeSampleStore(),
            producer=fake_producer,
            settings=dataclasses.replace(cfg, al_enabled=False),
        )
        return (lambda msg: run_once(graph, msg, cfg.judge_max_retries)), fake_producer, vlm, judge
    return _build


# ── 端到端：告警 → Kafka 2 ──────────────────────────────
def test_端到端_真警報送出相容格式訊息(build):
    run, producer, _, _ = build()

    run(ALERT_MESSAGE)

    topic, payload = producer.sent[0]
    assert topic == "processed-reports"
    # 既有欄位（舊 consumer 需要的）
    # device_id 直接沿用邊緣端算好的 301，不再因為缺 camera_id 而變成寫死的 101
    assert payload["device_id"] == 301
    assert payload["event_type"] == "fall"
    assert payload["detected_at"] == "2026-07-19T15:30:00"
    assert payload["snapshot_path"].endswith("snapshot_Room_301_Bed_20260719_153000.jpg")
    # vlm_summary 是 Agent 自己的判讀，不是邊緣端塞在訊息裡的那句佔位文字
    assert payload["vlm_summary"].startswith("VLM 報告")
    # 後端已移除的兩欄不外發（1bbb585）；yolo_threshold 只留在 Kafka 1 給 judge prompt 用
    assert "severity" not in payload
    assert "yolo_threshold" not in payload
    # 新增欄位
    assert payload["ai_verdict"] == "true_alarm"
    assert payload["ai_confidence"] == 0.9


def test_端到端_誤報只送建議(build):
    run, producer, _, _ = build(judge_script=[JudgeResult(
        verdict="false_alarm", confidence=0.8, reasoning="畫面中長者正常坐於椅上"
    )])

    run(ALERT_MESSAGE)

    payload = producer.sent[0][1]
    assert payload["ai_verdict"] == "false_alarm"
    assert payload["ai_reasoning"]
    # Agent 只給建議：訊息裡沒有任何可以直接關閉事件的欄位
    assert "status" not in payload
    assert "verdict" not in payload


# ── 巡檢路徑 ────────────────────────────────────────────
def test_巡檢訊息走巡檢路徑不觸發複判(build):
    run, producer, vlm, judge = build(vlm_script=["【安養中心智慧環境巡檢報告】一切正常"])

    run(ROUTINE_MESSAGE)

    assert judge.calls == 0                       # 完全沒動用複判
    assert "巡檢" in vlm.prompts[0]                # 用的是巡檢專屬 prompt
    payload = producer.sent[0][1]
    assert payload["ai_verdict"] is None          # 巡檢不做真假判定
    assert payload["vlm_summary"].startswith("【安養中心智慧環境巡檢報告】")


def test_分流判斷是純函式():
    alert = AlertMessage(event_type="Fall_Detected", camera_id="101")
    routine = AlertMessage(event_type="Routine_Environment_Sanity_Check", camera_id="101")

    assert route_after_ingest({"alert": alert}) == "review"
    assert route_after_ingest({"alert": routine}) == "routine"
    assert route_after_ingest({"error": "validation_failed: x"}) == "drop"


# ── 壞資料短路 ──────────────────────────────────────────
def test_壞資料不送_kafka_也不_crash(build, settings, read_jsonl):
    run, producer, vlm, judge = build()

    # 真正的壞資料：兩個裝置欄位都給不出編號（device_id 缺、camera_id 沒有數字）
    run({**ALERT_MESSAGE, "device_id": None, "camera_id": "Unknown_Room"})

    assert producer.sent == []
    assert vlm.prompts == []                      # 根本沒走到 VLM
    assert judge.calls == 0
    assert read_jsonl(settings.dlq_log_path)[0]["reason"] == "validation_failed"


def test_缺圖不送_kafka_也不_crash(build):
    from agent.image_store import ImageNotFound

    run, producer, _, _ = build(store=FakeStore(error=ImageNotFound("找不到圖檔")))

    run(ALERT_MESSAGE)

    assert producer.sent == []


# ── 降級：任何壞掉都不會變成誤報 ─────────────────────────
def test_VLM_全滅時仍送出訊息且交回人工(build):
    run, producer, _, judge = build(vlm_script=[VlmError("連不上")] * 3)

    run(ALERT_MESSAGE)

    payload = producer.sent[0][1]
    assert payload["ai_verdict"] is None          # 交回人工，不是誤報
    assert judge.calls == 0                       # 沒證據就不叫 LLM 硬掰
    assert "未取得影像判讀" in payload["vlm_summary"]


def test_judge_解析失敗時交回人工(build):
    run, producer, _, _ = build(judge_script=[ValueError("JSON 解析失敗")] * 5)

    run(ALERT_MESSAGE)

    assert producer.sent[0][1]["ai_verdict"] is None


# ── uncertain 補問迴圈 ──────────────────────────────────
def test_不確定時回頭補問_VLM_後改判(build):
    run, producer, vlm, judge = build(
        vlm_script=["畫面模糊", "補充後：長者倒臥地面，助行器翻倒"],
        judge_script=[
            JudgeResult(verdict="uncertain", confidence=0.3, reasoning="畫面模糊"),
            JudgeResult(verdict="true_alarm", confidence=0.85, reasoning="補問後確認跌倒"),
        ],
        judge_max_retries=1,
    )

    run(ALERT_MESSAGE)

    assert len(vlm.prompts) == 2
    assert "【補充追問】" in vlm.prompts[1]        # 第二次帶了追問
    assert producer.sent[0][1]["ai_verdict"] == "true_alarm"


def test_補問後仍不確定就交回人工(build):
    uncertain = JudgeResult(verdict="uncertain", confidence=0.3, reasoning="仍看不清")
    run, producer, vlm, judge = build(
        vlm_script=["畫面模糊", "還是模糊"],
        judge_script=[uncertain, uncertain],
        judge_max_retries=1,
    )

    run(ALERT_MESSAGE)

    assert judge.calls == 2                       # 補問一次後就停，不無限迴圈
    assert producer.sent[0][1]["ai_verdict"] is None


def test_補問次數為零時不補問(build):
    run, producer, vlm, judge = build(
        judge_script=[JudgeResult(verdict="uncertain", confidence=0.3,
                                  reasoning="模糊")],
        judge_max_retries=0,
    )

    run(ALERT_MESSAGE)

    assert len(vlm.prompts) == 1
    assert judge.calls == 1


# ── 主動學習策展接在圖裡 ────────────────────────────────
@pytest.fixture
def build_with_curation(settings, fake_producer):
    """策展開啟的圖；回傳 (跑一筆的函式, producer, sample_store)。"""
    import dataclasses

    def _build(curator_script, judge_script=None, message_verdict="true_alarm"):
        sample_store = FakeSampleStore()
        graph = build_graph(
            image_store=FakeStore(),
            vlm_client=ScriptedVlm(["VLM 報告：長者倒臥於地面"]),
            judge_model=ScriptedJudge(judge_script or [JudgeResult(
                verdict=message_verdict, confidence=0.9, reasoning="理由")]),
            curator_model=ScriptedJudge(curator_script),
            sample_store=sample_store,
            producer=fake_producer,
            settings=dataclasses.replace(settings, al_enabled=True),
        )
        return (lambda msg: run_once(graph, msg, settings.judge_max_retries)), fake_producer, sample_store
    return _build


def test_告警先送出再策展(settings, fake_producer):
    """策展是 LLM 呼叫（實測約 3 秒），排在 publish 前等於讓跌倒通知白等。

    這條測試釘住順序：告警必須先進 Kafka，樣本才慢慢挑。
    """
    import dataclasses

    from agent.schemas import ALDecision

    order = []

    class RecordingProducer:
        def send(self, topic, value=None):
            order.append("publish")

        def flush(self):
            pass

    class RecordingStore:
        def save(self, image_path, metadata):
            order.append("curate")
            return image_path

    graph = build_graph(
        image_store=FakeStore(),
        vlm_client=ScriptedVlm(["VLM 報告：長者倒臥於地面"]),
        judge_model=ScriptedJudge([JudgeResult(
            verdict="true_alarm", confidence=0.9, reasoning="理由")]),
        curator_model=ScriptedJudge([ALDecision(keep=True, reason="漏抓盲點", priority="high")]),
        sample_store=RecordingStore(),
        producer=RecordingProducer(),
        settings=dataclasses.replace(settings, al_enabled=True),
    )
    run_once(graph, ALERT_MESSAGE, settings.judge_max_retries)

    assert order == ["publish", "curate"], "告警必須先送出，策展不得擋在通知前面"


def test_策展在圖裡執行且不影響發布(build_with_curation):
    from agent.schemas import ALDecision

    run, producer, sample_store = build_with_curation(
        [ALDecision(keep=True, reason="YOLO 偏低但確認跌倒，屬漏抓盲點", priority="high")]
    )

    run(ALERT_MESSAGE)

    assert len(sample_store.saved) == 1                     # 樣本有收
    assert producer.sent[0][1]["ai_verdict"] == "true_alarm"  # 發布內容不受影響


def test_策展判定不收時發布照常(build_with_curation):
    from agent.schemas import ALDecision

    run, producer, sample_store = build_with_curation(
        [ALDecision(keep=False, reason="模型已經判得準", priority="low")]
    )

    run(ALERT_MESSAGE)

    assert sample_store.saved == []
    assert len(producer.sent) == 1


def test_策展壞掉不擋發布(build_with_curation):
    # 資料集是附加價值，事件該送還是要送
    run, producer, sample_store = build_with_curation([RuntimeError("策展模型爆炸")])

    run(ALERT_MESSAGE)

    assert len(producer.sent) == 1


def test_巡檢事件不經過策展(build_with_curation):
    run, producer, sample_store = build_with_curation([])   # 一被呼叫就會 IndexError

    run(ROUTINE_MESSAGE)

    assert sample_store.saved == []
    assert len(producer.sent) == 1


# ── Shadow 模式端到端 ───────────────────────────────────
def test_shadow_端到端零訊息但記錄完整(build, settings, read_jsonl):
    run, producer, _, _ = build(shadow_mode=True)

    run(ALERT_MESSAGE)

    assert producer.sent == []                    # Kafka 2 零訊息
    records = read_jsonl(settings.shadow_log_path)
    assert len(records) == 1
    assert records[0]["report"]["ai_verdict"] == "true_alarm"
    assert records[0]["report"]["ai_reasoning"]

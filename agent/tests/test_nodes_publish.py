# agent/tests/test_nodes_publish.py
# 驗收重點（WBS P1.5/P1.6）：輸出是現有格式的超集；uncertain → ai_verdict=null；
# shadow 下 Kafka 2 零訊息、判定記錄完整落地。

import pytest

from agent.nodes.publish import (
    SeenKeys,
    build_report,
    dedupe_key,
    make_publish_node,
    to_ai_verdict,
)
from agent.schemas import AlertMessage

ALERT = AlertMessage(
    event_type="Fall_Detected",
    camera_id="101",
    image_filename="snapshot_101.jpg",
    yolo_score=0.72,
    yolo_threshold=0.5,
    detected_at="2026-07-19T15:30:00",
    clip_path="/vids/xxx.mp4",
)
STATE = {
    "alert": ALERT,
    "image_path": "/imgs/snapshot_101.jpg",
    "vlm_report": "【安養中心緊急通報】長者倒臥於床邊地面",
    "verdict": "true_alarm",
    "confidence": 0.87,
    "reasoning": "VLM 確認人員倒臥於床邊地面，姿態與跌倒相符",
    "severity": "high",
}
NOW = "2026-07-19T16:00:00"


# ── 安全非對稱：對外只承認兩種 verdict ────────────────────
@pytest.mark.parametrize("verdict,expected", [
    ("true_alarm", "true_alarm"),
    ("false_alarm", "false_alarm"),
    ("uncertain", None),      # 判不出來 → 交回人工，不是猜一個誤報
    (None, None),
    ("", None),
    ("something_else", None),
])
def test_對外_verdict_轉換(verdict, expected):
    assert to_ai_verdict(verdict) == expected


def test_uncertain_送出時_ai_verdict_是_null():
    report = build_report({**STATE, "verdict": "uncertain"}, received_at=NOW)

    assert report.ai_verdict is None
    # 理由仍然送出去：前端要顯示「AI 無法判定」的說明給值班人員看
    assert report.ai_reasoning


# ── Kafka 2 是現有格式的超集 ────────────────────────────
def test_既有欄位語意不變():
    report = build_report(STATE, received_at=NOW)

    assert report.device_id == 101                       # camera_id 轉 int
    assert report.event_type == "Fall_Detected"
    assert report.clip_path == "/vids/xxx.mp4"
    assert report.detected_at == "2026-07-19T15:30:00"
    assert report.snapshot_path == "/imgs/snapshot_101.jpg"
    assert report.yolo_score == 0.72
    assert report.yolo_threshold == 0.5
    assert report.vlm_summary.startswith("【安養中心緊急通報】")
    assert report.severity == "high"


def test_舊_consumer_需要的欄位一個不少():
    # backend/kafka_consumer.py → EventCreateRequest 需要的欄位
    payload = build_report(STATE, received_at=NOW).model_dump()

    required = ["device_id", "event_type", "clip_path", "detected_at",
                "snapshot_path", "yolo_score", "yolo_threshold", "vlm_summary", "severity"]
    for field in required:
        assert payload[field] is not None, f"缺少既有欄位 {field}"


def test_缺_clip_path_時補現況的預設值():
    alert = ALERT.model_copy(update={"clip_path": None})

    report = build_report({**STATE, "alert": alert}, received_at=NOW)

    assert report.clip_path == "/vids/fallback.mp4"      # 沿用 vlm_worker 現況


def test_缺_detected_at_時用收到時間補():
    alert = ALERT.model_copy(update={"detected_at": None})

    report = build_report({**STATE, "alert": alert}, received_at=NOW)

    assert report.detected_at == NOW


def test_沒有_VLM_報告時仍送得出訊息():
    # vlm_summary 是後端必填語意欄位，不能是 None
    report = build_report({**STATE, "vlm_report": None, "verdict": "uncertain"}, received_at=NOW)

    assert "未取得影像判讀" in report.vlm_summary
    assert report.ai_verdict is None


# ── 冪等 ────────────────────────────────────────────────
def test_冪等鍵由裝置_時間_事件類型組成():
    assert dedupe_key(build_report(STATE, NOW)) == "101|2026-07-19T15:30:00|Fall_Detected"


def test_重複事件只送一次(fake_producer):
    publish = make_publish_node(fake_producer, "processed-reports",
                                shadow=False, shadow_log_path="/dev/null")

    first = publish(STATE)
    second = publish(STATE)

    assert first["published"] is True
    assert second["published"] is False
    assert second["skipped_reason"] == "duplicate"
    assert len(fake_producer.sent) == 1


def test_不同事件都會送出(fake_producer):
    publish = make_publish_node(fake_producer, "processed-reports",
                                shadow=False, shadow_log_path="/dev/null")
    other = {**STATE, "alert": ALERT.model_copy(update={"device_id": 102})}

    publish(STATE)
    publish(other)

    assert len(fake_producer.sent) == 2


def test_記憶上限之內先進先出():
    seen = SeenKeys(max_size=2)

    assert seen.seen("a") is False
    assert seen.seen("b") is False
    assert seen.seen("c") is False   # 塞爆，最舊的 a 被擠掉
    assert seen.seen("a") is False   # a 已被遺忘，會被當成新的
    assert seen.seen("c") is True


# ── 正式模式 ────────────────────────────────────────────
def test_正式模式送到正確的_topic_並_flush(fake_producer):
    publish = make_publish_node(fake_producer, "processed-reports",
                                shadow=False, shadow_log_path="/dev/null")

    publish(STATE)

    topic, payload = fake_producer.sent[0]
    assert topic == "processed-reports"
    assert payload["ai_verdict"] == "true_alarm"
    assert payload["ai_confidence"] == 0.87
    assert fake_producer.flushed == 1


# ── Shadow 模式 ─────────────────────────────────────────
def test_shadow_下一則都不送_kafka(fake_producer, tmp_path):
    publish = make_publish_node(fake_producer, "processed-reports",
                                shadow=True, shadow_log_path=str(tmp_path / "s.jsonl"))

    publish(STATE)

    assert fake_producer.sent == []
    assert fake_producer.flushed == 0


def test_shadow_下判定記錄完整落地(tmp_path, read_jsonl):
    log_path = tmp_path / "s.jsonl"
    publish = make_publish_node(None, "processed-reports",
                                shadow=True, shadow_log_path=str(log_path))

    out = publish(STATE)

    assert out["published"] is False
    assert out["skipped_reason"] == "shadow"
    records = read_jsonl(log_path)
    assert len(records) == 1
    assert records[0]["dedupe_key"] == "101|2026-07-19T15:30:00|Fall_Detected"
    assert records[0]["report"]["ai_verdict"] == "true_alarm"
    assert records[0]["report"]["ai_reasoning"]   # 比對報告要看得到理由


def test_shadow_下沒有_producer_也不會爆(tmp_path):
    # 正式路徑之外不該存在任何碰 Kafka 的可能，producer=None 就是最硬的保證
    publish = make_publish_node(None, "processed-reports",
                                shadow=True, shadow_log_path=str(tmp_path / "s.jsonl"))

    assert publish(STATE)["published"] is False

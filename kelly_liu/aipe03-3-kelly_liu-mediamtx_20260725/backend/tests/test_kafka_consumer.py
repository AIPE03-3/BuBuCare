from backend.kafka_consumer import classify_response


def test_201回ok():
    assert classify_response(201) == "ok"


def test_400回poison():
    assert classify_response(400) == "poison"


def test_422回poison():
    assert classify_response(422) == "poison"


def test_500回retry():
    assert classify_response(500) == "retry"


import json

from backend.kafka_consumer import handle_raw_message
from backend.core.models import DetectEvent


class _FakeResp:
    def __init__(self, status_code):
        self.status_code = status_code


def test_合法json_201回ok():
    assert handle_raw_message(b'{"device_id": 1}', lambda data: _FakeResp(201)) == "ok"


def test_合法json_400回poison():
    assert handle_raw_message(b'{"device_id": 999}', lambda data: _FakeResp(400)) == "poison"


def test_送出丟例外回retry():
    def boom(data):
        raise ConnectionError("server down")

    assert handle_raw_message(b'{"device_id": 1}', boom) == "retry"


def test_非法json回poison():
    assert handle_raw_message(b"not-json", lambda data: _FakeResp(201)) == "poison"


# ── 整合測試：post_fn 指向真的 /events 路由（免真 Kafka），驗證整條落 DB ──
def test_整合_合法訊息落DB(client, db_session):
    raw = json.dumps({
        "device_id": 1,
        "event_type": "fall",
        "clip_path": "s3://clips/k.mp4",
        "detected_at": "2026-07-02T14:30:00",
    }).encode()

    def post_fn(data):
        return client.post("/events", json=data, headers={"X-API-Key": "test-api-key"})

    assert handle_raw_message(raw, post_fn) == "ok"
    assert db_session.query(DetectEvent).count() == 1


def test_整合_裝置不存在回poison且不落DB(client, db_session):
    raw = json.dumps({
        "device_id": 999,
        "event_type": "fall",
        "clip_path": "s3://clips/k.mp4",
        "detected_at": "2026-07-02T14:30:00",
    }).encode()

    def post_fn(data):
        return client.post("/events", json=data, headers={"X-API-Key": "test-api-key"})

    assert handle_raw_message(raw, post_fn) == "poison"
    assert db_session.query(DetectEvent).count() == 0

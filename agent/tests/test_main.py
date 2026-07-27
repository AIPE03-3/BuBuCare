# agent/tests/test_main.py
# 消費迴圈的純邏輯測試（不碰 Kafka）：一筆壞訊息不該讓整個服務停擺。

import json

from agent.main import describe_settings, handle_raw_message, main


class FakeGraph:
    """假的圖：記錄收到什麼，或照設定丟例外。"""

    def __init__(self, error=None):
        self.error = error
        self.invoked = []

    def invoke(self, state, *args, **kwargs):
        self.invoked.append(state)
        if self.error:
            raise self.error
        return state


# ── handle_raw_message ──────────────────────────────────
def test_合法訊息交給圖處理(settings):
    graph = FakeGraph()
    raw = json.dumps({"event_type": "Fall_Detected", "camera_id": "101"}).encode()

    assert handle_raw_message(raw, graph, settings) == "ok"
    assert graph.invoked[0]["raw"]["camera_id"] == "101"


def test_補問上限被帶進初始_state(settings):
    graph = FakeGraph()

    handle_raw_message(b'{"camera_id": "101"}', graph, settings)

    assert graph.invoked[0]["judge_max_retries"] == settings.judge_max_retries


def test_壞_JSON_進_DLQ_不_crash(settings, read_jsonl):
    graph = FakeGraph()

    assert handle_raw_message(b"{not json", graph, settings) == "poison"
    assert graph.invoked == []
    assert read_jsonl(settings.dlq_log_path)[0]["reason"] == "bad_json"


def test_圖裡沒接住的例外進_DLQ_不_crash(settings, read_jsonl):
    # 消費迴圈是最後一道防線：任何漏網例外都要被接住，服務繼續跑
    graph = FakeGraph(error=RuntimeError("節點爆炸"))

    assert handle_raw_message(b'{"camera_id": "101"}', graph, settings) == "poison"
    record = read_jsonl(settings.dlq_log_path)[0]
    assert record["reason"] == "graph_error"
    assert "節點爆炸" in record["detail"]


def test_處理多筆時壞訊息不影響後續(settings):
    graph = FakeGraph()

    results = [
        handle_raw_message(b'{"camera_id": "101"}', graph, settings),
        handle_raw_message("壞資料".encode(), graph, settings),
        handle_raw_message(b'{"camera_id": "102"}', graph, settings),
    ]

    assert results == ["ok", "poison", "ok"]
    assert len(graph.invoked) == 2


# ── describe_settings（健檢報告）─────────────────────────
def test_健檢報告涵蓋關鍵設定(settings):
    text = describe_settings(settings)

    assert "nursing-home-alerts" in text
    assert "processed-reports" in text
    assert "ollama:qwen3" in text
    assert "llava:latest" in text
    assert settings.image_base_dir in text


def test_健檢報告標示_shadow_模式(make_settings):
    assert "SHADOW" in describe_settings(make_settings(shadow_mode=True))
    assert "正式" in describe_settings(make_settings(shadow_mode=False))


def test_健檢報告在_s3_模式顯示_bucket(make_settings):
    text = describe_settings(make_settings(image_source="s3", s3_bucket="my-bucket"))

    assert "my-bucket" in text


def test_健檢報告不外洩憑證(make_settings, monkeypatch):
    # 健檢輸出可能被貼到聊天室或 issue，不能夾帶任何金鑰
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "super-secret-value")

    text = describe_settings(make_settings())

    assert "super-secret-value" not in text


# ── CLI ─────────────────────────────────────────────────
def test_設定錯誤時回傳非零離開碼(monkeypatch, capsys):
    monkeypatch.delenv("AGENT_IMAGE_BASE_DIR", raising=False)
    monkeypatch.setenv("AGENT_IMAGE_SOURCE", "local")

    assert main(["--check-config"]) == 1
    assert "設定錯誤" in capsys.readouterr().err


def test_設定正確時健檢回傳零(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AGENT_IMAGE_SOURCE", "local")
    monkeypatch.setenv("AGENT_IMAGE_BASE_DIR", str(tmp_path))

    assert main(["--check-config"]) == 0
    assert "Agent 設定健檢" in capsys.readouterr().out

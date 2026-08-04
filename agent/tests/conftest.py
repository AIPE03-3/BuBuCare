# agent/tests/conftest.py
# Agent 測試的共用 fixtures。
# 目標：所有節點都能在「無網路、無 Kafka、無 Ollama」的環境下被單測，
# 所以外部依賴一律走注入點（settings / image store / LLM / producer）。

import json

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent.config import Settings


@pytest.fixture
def make_settings(tmp_path):
    """設定工廠：預設值就是一組能跑的開發設定，測試只覆寫自己在乎的欄位。

    圖檔目錄、log 檔都落在 tmp_path，測試之間互不干擾。
    """
    def _make(**overrides):
        defaults = dict(
            kafka_bootstrap_servers="localhost:9092",
            kafka_in_topic="nursing-home-alerts",
            kafka_out_topic="processed-reports",
            kafka_group_id="agent-reviewer-test",
            agent_llm="ollama:qwen2.5:7b",
            vlm_model="qwen2.5vl:7b",
            ollama_base_url="http://localhost:11434",
            image_source="local",
            image_base_dir=str(tmp_path / "images"),
            image_wait_seconds=0.0,      # 測試不要真的睡
            s3_bucket="",
            s3_prefix="",
            s3_region="ap-northeast-1",
            s3_cache_dir=str(tmp_path / "s3cache"),
            shadow_mode=False,
            vlm_max_retries=2,
            vlm_timeout_seconds=5.0,
            vlm_temperature=0.1,
            judge_max_retries=1,
            al_enabled=True,
            al_dataset_dir=str(tmp_path / "dataset"),
            al_fallback_min_score=0.35,
            al_fallback_max_score=0.85,
            dlq_log_path=str(tmp_path / "dlq.jsonl"),
            shadow_log_path=str(tmp_path / "shadow.jsonl"),
        )
        defaults.update(overrides)
        return Settings(**defaults)
    return _make


@pytest.fixture
def settings(make_settings):
    return make_settings()


@pytest.fixture
def image_dir(tmp_path):
    """本機圖檔目錄；回傳一個「放一張假圖進去」的函式。"""
    directory = tmp_path / "images"
    directory.mkdir(exist_ok=True)

    def _put(filename: str, content: bytes = b"fake-jpeg-bytes") -> str:
        path = directory / filename
        path.write_bytes(content)
        return str(path)

    _put.dir = directory
    return _put


@pytest.fixture
def fake_llm():
    """假的 chat model 工廠：照著給定的回覆序列吐內容，不連任何服務。

    用法：fake_llm(["第一次回覆", "第二次回覆"])
    """
    def _make(responses: list[str]):
        return GenericFakeChatModel(messages=iter([AIMessage(content=r) for r in responses]))
    return _make


@pytest.fixture
def fake_structured_llm():
    """假的 structured output 模型：直接回傳預先準備好的物件，或丟出例外。

    judge 的降級路徑（解析失敗 → ai_verdict=null）就是靠丟例外這條路測的。
    """
    class _FakeStructured:
        def __init__(self, results):
            # results 每個元素可以是 Pydantic 物件，或 Exception（模擬解析失敗）
            self._results = list(results)
            self.calls = []

        def invoke(self, messages, *args, **kwargs):
            self.calls.append(messages)
            if not self._results:
                raise AssertionError("fake_structured_llm 被呼叫的次數超過準備好的回覆數")
            result = self._results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

    return _FakeStructured


@pytest.fixture
def fake_producer():
    """假的 Kafka producer：把送出的訊息留在記憶體裡供斷言。"""
    class _FakeProducer:
        def __init__(self):
            self.sent = []
            self.flushed = 0

        def send(self, topic, value=None):
            self.sent.append((topic, value))

        def flush(self):
            self.flushed += 1

    return _FakeProducer()


@pytest.fixture
def read_jsonl():
    """讀 JSON lines 檔（DLQ / shadow 記錄的斷言用）；檔案不存在回空 list。"""
    def _read(path):
        try:
            with open(path, encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()]
        except FileNotFoundError:
            return []
    return _read

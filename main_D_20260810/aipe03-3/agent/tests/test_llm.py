# agent/tests/test_llm.py
# 驗收重點（WBS P0.3）：預設值下無任何雲端依賴可跑；切換環境變數即換後端，零程式碼改動。

import pytest

from agent.config import ConfigError
from agent.llm import build_chat_model


@pytest.fixture
def spy_init(monkeypatch):
    """攔住 init_chat_model：測「我們傳了什麼給它」，不需要真的連 Ollama。"""
    calls = []

    def _fake(model, *, model_provider=None, **kwargs):
        calls.append({"model": model, "provider": model_provider, "kwargs": kwargs})
        return object()

    monkeypatch.setattr("agent.llm.init_chat_model", _fake)
    return calls


def test_預設走地端_ollama(settings, spy_init):
    build_chat_model(settings)

    assert spy_init[0]["provider"] == "ollama"
    assert spy_init[0]["model"] == "qwen3"
    assert spy_init[0]["kwargs"]["base_url"] == "http://localhost:11434"


def test_切雲端只改環境變數且不傳_base_url(make_settings, spy_init):
    # base_url 是 Ollama 專屬參數，傳給雲端 provider 會爆
    build_chat_model(make_settings(agent_llm="anthropic:claude-haiku-4-5-20251001"))

    assert spy_init[0]["provider"] == "anthropic"
    assert spy_init[0]["model"] == "claude-haiku-4-5-20251001"
    assert "base_url" not in spy_init[0]["kwargs"]


def test_模型名可含冒號(make_settings, spy_init):
    # 例如 ollama:qwen3:8b —— 只切第一個冒號
    build_chat_model(make_settings(agent_llm="ollama:qwen3:8b"))

    assert spy_init[0]["model"] == "qwen3:8b"


def test_呼叫端可透傳參數(settings, spy_init):
    build_chat_model(settings, temperature=0)

    assert spy_init[0]["kwargs"]["temperature"] == 0


def test_呼叫端可覆寫_base_url(make_settings, spy_init):
    build_chat_model(make_settings(), base_url="http://gpu-box:11434")

    assert spy_init[0]["kwargs"]["base_url"] == "http://gpu-box:11434"


@pytest.mark.parametrize("bad_spec", ["qwen3", "ollama:", ":qwen3", ""])
def test_格式錯誤報清楚的錯(make_settings, bad_spec):
    with pytest.raises(ConfigError, match="AGENT_LLM"):
        build_chat_model(make_settings(agent_llm=bad_spec))

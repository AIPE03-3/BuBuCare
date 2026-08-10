# agent/llm.py
"""LLM factory：所有 LLM 呼叫都從這裡拿模型，程式碼中不得出現寫死的模型名。

開發期預設是純地端 Ollama（AGENT_LLM=ollama:qwen2.5:7b），零 API 成本、零雲端依賴。
未來要切雲端只改環境變數：
    AGENT_LLM=anthropic:claude-haiku-4-5-20251001
不改任何一行程式碼（已拍板決策，見 agent/docs/01-architecture.md §4）。

VLM 走另一條路：Ollama 的多模態呼叫要傳本機圖檔路徑，用 ollama 原生 client 最直接，
所以這裡只提供推理腦（judge / drafter / 問答）。VLM 客戶端在 nodes/vlm.py。
"""
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from agent.config import ConfigError, Settings


def build_chat_model(settings: Settings, **kwargs) -> BaseChatModel:
    """依 settings.agent_llm（格式 "provider:model"）建出推理用的 chat model。

    kwargs 直接透傳給底層（temperature 之類），呼叫端要調參不必改這支。
    """
    spec = settings.agent_llm.strip()
    if ":" not in spec:
        raise ConfigError(
            f"AGENT_LLM 格式必須是 provider:model（例如 ollama:qwen2.5:7b），目前是 {spec!r}"
        )

    provider, model = spec.split(":", 1)
    provider = provider.strip()
    model = model.strip()
    if not provider or not model:
        raise ConfigError(f"AGENT_LLM 的 provider 與 model 都不能空白，目前是 {spec!r}")

    # 地端 Ollama 要知道服務位置；雲端 provider 沒有這個參數，傳進去會爆，所以只在 ollama 補
    if provider == "ollama":
        kwargs.setdefault("base_url", settings.ollama_base_url)

    return init_chat_model(model, model_provider=provider, **kwargs)


def build_structured_model(settings: Settings, schema, **kwargs):
    """要 LLM 吐固定形狀（Pydantic model）時用這支。

    地端小模型的 structured output 穩定度低於雲端，**解析失敗是預期中的常態**，
    所以呼叫端（judge）必須自己接住例外並降級為 ai_verdict=null，
    不能假設這裡一定給得出合法結果。
    """
    return build_chat_model(settings, **kwargs).with_structured_output(schema)

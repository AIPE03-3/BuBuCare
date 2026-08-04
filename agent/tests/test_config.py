# agent/tests/test_config.py
# 驗收重點（WBS P0.2）：無任何寫死路徑或模型名；缺必要變數時啟動報清楚的錯。

import pytest

from agent.config import ConfigError, load_settings

# load_settings() 讀的是真實環境變數，測試前必須把相關變數清乾淨，
# 否則開發者本機 .env 的值會漏進來，讓測試在別人機器上結果不同
AGENT_ENV_VARS = [
    "AGENT_KAFKA_BOOTSTRAP_SERVERS", "AGENT_KAFKA_IN_TOPIC", "AGENT_KAFKA_OUT_TOPIC",
    "AGENT_KAFKA_GROUP_ID", "AGENT_LLM", "AGENT_VLM_MODEL", "OLLAMA_BASE_URL",
    "AGENT_IMAGE_SOURCE", "AGENT_IMAGE_BASE_DIR", "AGENT_IMAGE_WAIT_SECONDS",
    "AGENT_S3_BUCKET", "AGENT_S3_PREFIX", "AGENT_S3_REGION", "AGENT_S3_CACHE_DIR",
    "AGENT_SHADOW", "AGENT_VLM_MAX_RETRIES", "AGENT_VLM_TIMEOUT_SECONDS", "AGENT_VLM_TEMPERATURE",
    "AGENT_JUDGE_MAX_RETRIES", "AGENT_DLQ_LOG_PATH", "AGENT_SHADOW_LOG_PATH",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in AGENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_預設是本機開發設定_只需給圖檔目錄(monkeypatch, tmp_path):
    # 已拍板：預設值即開發環境，無任何雲端依賴也能完整跑通
    monkeypatch.setenv("AGENT_IMAGE_BASE_DIR", str(tmp_path))

    settings = load_settings()

    assert settings.agent_llm == "ollama:qwen2.5:7b"   # 地端模型，零 API 成本
    assert settings.image_source == "local"
    assert settings.shadow_mode is False
    assert settings.kafka_in_topic == "nursing-home-alerts"
    assert settings.kafka_out_topic == "processed-reports"


def test_agent_的_group_id_不能跟_vlm_worker_相同(monkeypatch, tmp_path):
    # shadow 階段兩個服務要併行消費同一個 topic，group_id 撞在一起會互搶訊息
    monkeypatch.setenv("AGENT_IMAGE_BASE_DIR", str(tmp_path))

    assert load_settings().kafka_group_id != "vlm-brain-cluster"


def test_local_來源缺圖檔目錄時報清楚的錯():
    with pytest.raises(ConfigError, match="AGENT_IMAGE_BASE_DIR"):
        load_settings()


def test_s3_來源缺_bucket_時報清楚的錯(monkeypatch):
    monkeypatch.setenv("AGENT_IMAGE_SOURCE", "s3")

    with pytest.raises(ConfigError, match="AGENT_S3_BUCKET"):
        load_settings()


def test_s3_來源不需要本機圖檔目錄(monkeypatch):
    # 部署到別台機器時只會設 S3 變數，不該逼人填一個用不到的本機目錄
    monkeypatch.setenv("AGENT_IMAGE_SOURCE", "s3")
    monkeypatch.setenv("AGENT_S3_BUCKET", "my-bucket")

    settings = load_settings()

    assert settings.image_source == "s3"
    assert settings.s3_bucket == "my-bucket"


def test_未知的圖檔來源被擋下(monkeypatch):
    monkeypatch.setenv("AGENT_IMAGE_SOURCE", "ftp")

    with pytest.raises(ConfigError, match="local 或 s3"):
        load_settings()


def test_vlm溫度預設值是_0點1(monkeypatch, tmp_path):
    # 實測 llava 同張圖同提示在預設溫度下會隨機拒答，降溫是最小成本的緩解手段
    monkeypatch.setenv("AGENT_IMAGE_BASE_DIR", str(tmp_path))

    settings = load_settings()

    assert settings.vlm_temperature == 0.1


def test_數字型變數給非數字時報清楚的錯(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_IMAGE_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("AGENT_VLM_TIMEOUT_SECONDS", "很久")

    with pytest.raises(ConfigError, match="AGENT_VLM_TIMEOUT_SECONDS"):
        load_settings()


@pytest.mark.parametrize("raw,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("", False), ("no", False),
])
def test_shadow_開關的各種寫法(monkeypatch, tmp_path, raw, expected):
    monkeypatch.setenv("AGENT_IMAGE_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("AGENT_SHADOW", raw)

    assert load_settings().shadow_mode is expected


def test_切雲端模型只需改環境變數(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_IMAGE_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("AGENT_LLM", "anthropic:claude-haiku-4-5-20251001")

    assert load_settings().agent_llm == "anthropic:claude-haiku-4-5-20251001"

# agent/config.py
"""集中管理 Agent 的所有環境設定：整個 agent/ 只有這一支會讀環境變數。

比照 backend/core/config.py 的做法（設定收攏在一支），但改成「函式回傳 dataclass」而非
module 層常數——因為 agent 的測試要在同一個行程內反覆換設定（local/s3 圖檔來源、
shadow 開關），module 層常數在 import 當下就凍住，測試改不動。

設計原則：
1. 程式碼中不得出現寫死的模型名或路徑（順手修掉 vlm_worker.py 寫死 /Users/albert/... 的問題）。
2. 缺必要變數時在啟動當下就報清楚的錯，不要跑到一半才爆。
"""
import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()  # 讀 repo 根目錄的 .env


class ConfigError(Exception):
    # 設定不完整。由 main.py 在啟動時接住，印出人看得懂的訊息後結束
    pass


@dataclass(frozen=True)
class Settings:
    # ── Kafka ────────────────────────────────────────────
    kafka_bootstrap_servers: str
    kafka_in_topic: str          # Kafka 1：邊緣端告警
    kafka_out_topic: str         # Kafka 2：給 backend/kafka_consumer.py
    kafka_group_id: str

    # ── LLM ──────────────────────────────────────────────
    agent_llm: str               # 推理腦，格式 "provider:model"，如 ollama:qwen3
    vlm_model: str               # 視覺複判模型，如 llava:latest
    ollama_base_url: str

    # ── 圖檔來源（見 agent/docs/01-architecture.md §8）──
    image_source: str            # "local" | "s3"
    image_base_dir: str          # image_source=local 時必填
    image_wait_seconds: float    # 檔案還沒落地時的等待上限（沿用現況 vlm_worker 行為）
    s3_bucket: str               # image_source=s3 時必填
    s3_prefix: str
    s3_region: str
    s3_cache_dir: str            # S3 下載後的本機暫存目錄（VLM 只吃本機路徑）

    # ── 行為開關與閾值 ────────────────────────────────────
    shadow_mode: bool            # True：判定只寫 log，不送 Kafka 2
    vlm_max_retries: int
    vlm_timeout_seconds: float
    judge_max_retries: int       # judge 判 uncertain 時回頭補問 VLM 的次數上限

    # ── 主動學習樣本收錄 ──────────────────────────────────
    al_enabled: bool             # 關掉就完全不收樣本（例如壓測時不想灌爆硬碟）
    al_dataset_dir: str          # 樣本落地目錄，沿用現況的 active_learning_dataset
    al_fallback_min_score: float # curator 失效時的退路規則下限（沿用現況 0.35）
    al_fallback_max_score: float # 退路規則上限（沿用現況 0.85）

    # ── 落地檔案 ──────────────────────────────────────────
    dlq_log_path: str            # 壞訊息記錄（JSON lines）
    shadow_log_path: str         # shadow 模式的判定記錄（JSON lines）


def _get_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _get_float(name: str, default: str) -> float:
    raw = os.getenv(name, default)
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name} 必須是數字，目前是 {raw!r}")


def _get_int(name: str, default: str) -> int:
    raw = os.getenv(name, default)
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name} 必須是整數，目前是 {raw!r}")


def load_settings() -> Settings:
    """從環境變數組出設定；缺必要變數直接丟 ConfigError。

    「必要」是依 AGENT_IMAGE_SOURCE 決定的：選 local 就必須有 base dir，
    選 s3 就必須有 bucket。與其兩個都設成必填逼開發者填假值，不如按實際選擇檢查。
    """
    image_source = os.getenv("AGENT_IMAGE_SOURCE", "local").strip().lower()
    if image_source not in ("local", "s3"):
        raise ConfigError(f"AGENT_IMAGE_SOURCE 只能是 local 或 s3，目前是 {image_source!r}")

    image_base_dir = os.getenv("AGENT_IMAGE_BASE_DIR", "").strip()
    if image_source == "local" and not image_base_dir:
        raise ConfigError("AGENT_IMAGE_SOURCE=local 時必須設定 AGENT_IMAGE_BASE_DIR（圖檔目錄）")

    s3_bucket = os.getenv("AGENT_S3_BUCKET", "").strip()
    if image_source == "s3" and not s3_bucket:
        raise ConfigError("AGENT_IMAGE_SOURCE=s3 時必須設定 AGENT_S3_BUCKET")

    return Settings(
        kafka_bootstrap_servers=os.getenv("AGENT_KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        kafka_in_topic=os.getenv("AGENT_KAFKA_IN_TOPIC", "nursing-home-alerts"),
        kafka_out_topic=os.getenv("AGENT_KAFKA_OUT_TOPIC", "processed-reports"),
        # 刻意跟 vlm_worker 的 group_id（vlm-brain-cluster）不同：
        # shadow 階段兩者要能併行消費同一個 topic，各自拿到完整訊息
        kafka_group_id=os.getenv("AGENT_KAFKA_GROUP_ID", "agent-reviewer"),
        agent_llm=os.getenv("AGENT_LLM", "ollama:qwen3"),
        vlm_model=os.getenv("AGENT_VLM_MODEL", "llava:latest"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        image_source=image_source,
        image_base_dir=image_base_dir,
        image_wait_seconds=_get_float("AGENT_IMAGE_WAIT_SECONDS", "2.0"),
        s3_bucket=s3_bucket,
        s3_prefix=os.getenv("AGENT_S3_PREFIX", "").strip(),
        s3_region=os.getenv("AGENT_S3_REGION", "ap-northeast-1"),
        s3_cache_dir=os.getenv("AGENT_S3_CACHE_DIR", "/tmp/agent-image-cache"),
        shadow_mode=_get_bool("AGENT_SHADOW", "0"),
        vlm_max_retries=_get_int("AGENT_VLM_MAX_RETRIES", "2"),
        vlm_timeout_seconds=_get_float("AGENT_VLM_TIMEOUT_SECONDS", "120"),
        judge_max_retries=_get_int("AGENT_JUDGE_MAX_RETRIES", "1"),
        al_enabled=_get_bool("AGENT_AL_ENABLED", "1"),
        al_dataset_dir=os.getenv("AGENT_AL_DATASET_DIR", "active_learning_dataset"),
        # 這兩個數字是 vlm_worker.py:136 的寫死區間，搬進設定當作 curator 失效時的退路，
        # 不是主要判斷依據——主要依據是 al_curator 的 LLM 判斷
        al_fallback_min_score=_get_float("AGENT_AL_FALLBACK_MIN_SCORE", "0.35"),
        al_fallback_max_score=_get_float("AGENT_AL_FALLBACK_MAX_SCORE", "0.85"),
        dlq_log_path=os.getenv("AGENT_DLQ_LOG_PATH", "agent_dlq.jsonl"),
        shadow_log_path=os.getenv("AGENT_SHADOW_LOG_PATH", "agent_shadow.jsonl"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # 正式路徑用這支（只讀一次）；測試要換設定就直接呼叫 load_settings() 自己傳進去
    return load_settings()

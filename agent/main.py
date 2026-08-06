# agent/main.py
# Agent 服務入口。啟動：python -m agent.main
# 設定健檢：python -m agent.main --check-config
#
# 比照 backend/kafka_consumer.py 的分層風格：純邏輯（describe_settings / handle_raw_message）
# 與碰外部的東西（build_consumer / run）分開，前者可以單測。

import argparse
import json
import logging
import sys

from agent.config import ConfigError, Settings, load_settings
from agent.graph import build_graph, run_once
from agent.image_store import build_image_store
from agent.jsonl import append_jsonl
from agent.llm import build_structured_model
from agent.nodes.vlm import build_vlm_client
from agent.sample_store import ActiveLearningStore
from agent.schemas import ALDecision, JudgeResult

logger = logging.getLogger("agent")


def describe_settings(settings: Settings) -> str:
    """把設定整理成人看得懂的健檢報告。

    純函式（吃 Settings、吐字串），可以直接單測，不必真的啟動服務。
    刻意不印任何憑證：AWS 金鑰、API key 一律不經過這裡。
    """
    lines = [
        "── Agent 設定健檢 ──",
        f"Kafka       : {settings.kafka_bootstrap_servers}",
        f"  輸入 topic : {settings.kafka_in_topic}（group={settings.kafka_group_id}）",
        f"  輸出 topic : {settings.kafka_out_topic}",
        f"推理模型     : {settings.agent_llm}",
        f"視覺模型     : {settings.vlm_model} @ {settings.ollama_base_url}",
        f"圖檔來源     : {settings.image_source}",
    ]
    if settings.image_source == "local":
        lines.append(f"  目錄       : {settings.image_base_dir}")
    else:
        lines.append(f"  bucket     : {settings.s3_bucket}/{settings.s3_prefix}")
        lines.append(f"  暫存目錄    : {settings.s3_cache_dir}")

    mode = "SHADOW（只寫 log，不送 Kafka 2）" if settings.shadow_mode else "正式（送 Kafka 2）"
    lines.append(f"執行模式     : {mode}")
    lines.append(f"DLQ 記錄     : {settings.dlq_log_path}")
    if settings.shadow_mode:
        lines.append(f"判定記錄     : {settings.shadow_log_path}")
    return "\n".join(lines)


def handle_raw_message(raw: bytes | str, graph, settings: Settings) -> str:
    """處理一則原始訊息，回傳 "ok" 或 "poison"。

    刻意沒有 "retry"：跟 backend/kafka_consumer.py 不同，Agent 沒有「送不出去的一時失敗」
    ——VLM 失敗、judge 解析失敗都已經在節點內降級成「交回人工」的正常產出了。
    真的整張圖爆掉才算毒訊息，記 DLQ 後前進，不讓一筆訊息卡死整條線。
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
        append_jsonl(settings.dlq_log_path, {"reason": "bad_json", "detail": str(e), "raw": str(raw)})
        return "poison"

    try:
        run_once(graph, data, settings.judge_max_retries)
    except Exception as e:
        # 圖裡沒接住的例外：記下來繼續跑，一筆訊息不該讓整個服務停擺
        logger.exception("處理訊息時發生未預期例外")
        append_jsonl(settings.dlq_log_path, {"reason": "graph_error", "detail": str(e), "raw": data})
        return "poison"

    return "ok"


def build_consumer(settings: Settings):
    # lazy import：純邏輯測試不必先裝 kafka 套件
    from kafka import KafkaConsumer

    return KafkaConsumer(
        settings.kafka_in_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers.split(","),
        group_id=settings.kafka_group_id,
        enable_auto_commit=False,   # 處理完才手動 commit（at-least-once）
        auto_offset_reset="latest",
        # 一次只取一則。**這行不能拿掉**，2026-08-06 四台相機實跑時被這個打死過：
        # kafka-python 的 max_poll_records 預設是 500，而本 agent 每則要跑一次 VLM
        # 判讀（約 6 秒）加一次 judge，一則約 8 秒。只要單次 poll 拿回超過約 37 則，
        # 兩次 poll() 之間就會超過 max_poll_interval_ms（預設 300 秒），Kafka 會判定
        # 這個 consumer 掛了、把 partition 收走給別人，接著 commit 就噴
        # CommitFailedError（group has already rebalanced）。
        #
        # 症狀很難認：**行程還活著、log 也不再報錯，但它已經不在 group 裡、一則都不處理**，
        # 看起來就像 agent 靜靜地停擺，事件永遠停在「二審判讀中」。
        # 事件量低的時候一次拿不到幾則，所以單台相機測不出來。
        #
        # 設 1 讓 poll 迴圈每約 8 秒就回到 poll() 一次，離 300 秒門檻很遠。
        # 代價是每則多一次 fetch 往返，相對於 8 秒的判讀完全可以忽略。
        max_poll_records=1,
        # 不設 value_deserializer：拿原始 bytes 交給 handle_raw_message 自己解析，
        # 壞 JSON 才能在函式內被接住判成 poison，而不是在迭代時噴例外
    )


def build_producer(settings: Settings):
    # shadow 模式一則都不會送，就不要建連線——也順便確保那條路徑真的碰不到 Kafka
    if settings.shadow_mode:
        logger.info("SHADOW 模式：不建立 Kafka producer")
        return None

    from kafka import KafkaProducer

    return KafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers.split(","),
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
    )


def build_runtime(settings: Settings):
    """把所有外部依賴組起來，交給 build_graph。集中在這裡，其餘程式碼不自己建連線。"""
    return build_graph(
        image_store=build_image_store(settings),
        vlm_client=build_vlm_client(settings),
        judge_model=build_structured_model(settings, JudgeResult, temperature=0),
        curator_model=build_structured_model(settings, ALDecision, temperature=0),
        sample_store=ActiveLearningStore(settings.al_dataset_dir),
        producer=build_producer(settings),
        settings=settings,
    )


def run(settings: Settings) -> None:
    graph = build_runtime(settings)
    consumer = build_consumer(settings)
    logger.info(
        "Agent 啟動，監聽 topic=%s group=%s 模式=%s",
        settings.kafka_in_topic,
        settings.kafka_group_id,
        "SHADOW" if settings.shadow_mode else "正式",
    )
    try:
        for message in consumer:
            handle_raw_message(message.value, graph, settings)
            consumer.commit()   # ok 或 poison 都前進：毒訊息已進 DLQ，重試也不會變好
    except KeyboardInterrupt:
        logger.info("收到中斷，關閉 consumer")
    finally:
        consumer.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agent.main",
        description="AI Agent 複判服務：消費 Kafka 告警、指揮 VLM 複判、產出 verdict 建議。",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="只檢查環境設定並印出摘要，不啟動服務",
    )
    args = parser.parse_args(argv)

    # 設定壞掉就在啟動當下結束，不要跑到收訊息才爆
    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"設定錯誤：{e}", file=sys.stderr)
        return 1

    print(describe_settings(settings))
    if args.check_config:
        return 0

    run(settings)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())

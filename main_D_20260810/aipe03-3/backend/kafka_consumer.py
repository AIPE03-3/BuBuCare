# backend/kafka_consumer.py
# Kafka consumer：消費 processed-reports，每則轉打 POST /events。
# 啟動（先 cd backend）：python -m kafka_consumer
# 純邏輯（classify_response / handle_raw_message）與碰外部（post_event / build_consumer / run）分層。

import json
import logging
import time

import httpx

from core.config import (
    EVENT_API_KEY,
    EVENTS_URL,
    KAFKA_BOOTSTRAP_SERVERS,
    KAFKA_GROUP_ID,
    KAFKA_TOPIC,
    RETRY_SLEEP_SECONDS,
)

logger = logging.getLogger("kafka_consumer")


def classify_response(status_code: int) -> str:
    # 201 建立成功；400/422 是毒訊息（重試無用，跳過）；其餘（5xx/未知）當一時失敗重試
    if status_code == 201:
        return "ok"
    if status_code in (400, 422):
        return "poison"
    return "retry"


def handle_raw_message(raw, post_fn) -> str:
    # 1. 解析：解析不了就是壞資料（毒訊息）
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return "poison"
    # 2. 送出：送出階段任何例外＝傳輸失敗（一時的），回 retry
    #    注意：壞資料是靠「回應碼」判斷（下一步 classify_response），不是靠例外
    try:
        response = post_fn(data)
    except Exception:
        return "retry"
    # 3. 依回應碼判定
    return classify_response(response.status_code)


def post_event(data: dict):
    # 真正的送出動作：把一筆事件 POST 給自家 /events，帶機器驗證 key
    return httpx.post(
        EVENTS_URL,
        json=data,
        headers={"X-API-Key": EVENT_API_KEY},
        timeout=10,
    )


def build_consumer():
    # lazy import：讓 Task 1/2 的純邏輯測試不必先裝 kafka 套件
    from kafka import KafkaConsumer

    return KafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS.split(","),
        group_id=KAFKA_GROUP_ID,
        enable_auto_commit=False,   # 處理成功才手動 commit（at-least-once）
        auto_offset_reset="latest",  # 首次啟動只收「從現在開始」的新警報
        # 不設 value_deserializer：拿原始 bytes 交給 handle_raw_message 自己解析，
        # 壞 JSON 才能在函式內被接住判成 poison，而不是在迭代時噴例外
    )


def run():
    consumer = build_consumer()
    logger.info("consumer 啟動，監聽 topic=%s bootstrap=%s", KAFKA_TOPIC, KAFKA_BOOTSTRAP_SERVERS)
    try:
        for message in consumer:
            # 對「同一則」重試直到 ok/poison，期間不 commit（server 恢復前不掉件）
            while True:
                decision = handle_raw_message(message.value, post_event)
                if decision == "retry":
                    logger.warning("送出失敗（一時），%s 秒後重試", RETRY_SLEEP_SECONDS)
                    time.sleep(RETRY_SLEEP_SECONDS)
                    continue
                if decision == "poison":
                    # 毒訊息：本次僅記 log（未來可在此改丟 dead-letter queue）
                    logger.error("毒訊息，跳過：%r", message.value)
                consumer.commit()  # ok 或 poison 都前進
                break
    except KeyboardInterrupt:
        logger.info("收到中斷，關閉 consumer")
    finally:
        consumer.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()

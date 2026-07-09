# kafka_consumer.py
# Kafka consumer：消費 processed-reports，每則轉打 POST /events。
# 純邏輯（classify_response / handle_raw_message）與碰外部（post_event / build_consumer / run）分層。

import json


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

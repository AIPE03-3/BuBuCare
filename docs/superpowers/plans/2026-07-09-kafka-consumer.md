# Kafka Consumer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `kafka_consumer.py`，消費 Kafka topic `processed-reports`，每則訊息轉打 `POST /events`，達成 Kafka → DB → SSE 接通。

**Architecture:** 方案 B——consumer 是獨立行程，不直接碰 DB/SSE，而是把訊息 POST 給現成的 `POST /events`，由 FastAPI 行程完成寫 DB + SSE 廣播（避免跨行程 broadcast 到空 pool）。程式切成純邏輯（`classify_response`、`handle_raw_message`）與碰外部世界（`post_event`、`build_consumer`、`run`）兩層，純邏輯用依賴注入（`post_fn`）達成免真 Kafka/server 可測。

**Tech Stack:** Python 3.12、uv、kafka-python-ng（消費）、httpx（打 HTTP）、pytest。

## Global Constraints

- 套件管理用 **uv**；測試用 `uv run pytest tests/ -v`，全新 PowerShell session 用完整路徑 `& "C:\Users\user\Projects\fulilian-backend\.venv\Scripts\python.exe" -m pytest tests/ -v`。
- **不得修改** `event_service.py` / `event_routes.py` / `models.py` / `sse.py` / `main.py`。允許修改的既有檔案只有 `.env.example`、`pyproject.toml`。
- 錯誤處理三分類固定為字串 `"ok"` / `"poison"` / `"retry"`。
- `enable_auto_commit=False`，處理成功（ok/poison）才 commit；`auto_offset_reset="latest"`；topic 固定 `processed-reports`；group_id 固定 `fulilian-backend`。
- 毒訊息本次僅 log（保留掛勾，之後可升級 DLQ）。
- git commit 訊息結尾加：`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`（實際 commit 由使用者確認，見 CLAUDE.md）。

## File Structure

| 檔案 | 責任 |
| --- | --- |
| `kafka_consumer.py`（新增） | 五個函式：`classify_response`、`handle_raw_message`、`post_event`、`build_consumer`、`run` |
| `tests/test_kafka_consumer.py`（新增） | 純邏輯單元測試 + 用 TestClient 的整合測試 |
| `.env.example`（修改） | 加 `KAFKA_BOOTSTRAP_SERVERS`、`EVENTS_URL` |
| `pyproject.toml`（修改） | httpx 由 dev 移到正式 dependencies；加 kafka-python-ng |

**匯入策略**：`from kafka import KafkaConsumer` 放在 `build_consumer()` 內部（lazy import），`import httpx` 只在 Task 3 才加入。這樣 Task 1/2 的測試不需先裝 kafka-python-ng 也能跑。

**Docker 前置**：只有 Task 3 的 Step 6（端到端煙霧測試）需要真的 Kafka broker（本機用 Docker 起）。若尚未安裝 Docker，Task 1–2 與 Task 3 的 Step 1–5 皆可照常完成——自動化測試不需 Docker/Kafka；Step 6 延後到裝好 Docker 再做。

---

### Task 1: `classify_response`（回應碼 → 決定）

**Files:**
- Create: `kafka_consumer.py`
- Test: `tests/test_kafka_consumer.py`

**Interfaces:**
- Consumes: 無
- Produces: `classify_response(status_code: int) -> str`，回傳 `"ok"`（201）/ `"poison"`（400、422）/ `"retry"`（其他）

- [ ] **Step 1: 寫失敗測試**

`tests/test_kafka_consumer.py`：
```python
from kafka_consumer import classify_response


def test_201回ok():
    assert classify_response(201) == "ok"


def test_400回poison():
    assert classify_response(400) == "poison"


def test_422回poison():
    assert classify_response(422) == "poison"


def test_500回retry():
    assert classify_response(500) == "retry"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_kafka_consumer.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'kafka_consumer'`

- [ ] **Step 3: 寫最小實作**

`kafka_consumer.py`：
```python
# kafka_consumer.py
# Kafka consumer（方案 B）：消費 processed-reports，每則轉打 POST /events。
# 純邏輯（classify_response / handle_raw_message）與碰外部（post_event / build_consumer / run）分層。


def classify_response(status_code: int) -> str:
    # 201 建立成功；400/422 是毒訊息（重試無用，跳過）；其餘（5xx/未知）當一時失敗重試
    if status_code == 201:
        return "ok"
    if status_code in (400, 422):
        return "poison"
    return "retry"
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_kafka_consumer.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add kafka_consumer.py tests/test_kafka_consumer.py
git commit -m "feat: kafka consumer 的 classify_response（回應碼分類）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `handle_raw_message`（處理一則訊息）

**Files:**
- Modify: `kafka_consumer.py`
- Test: `tests/test_kafka_consumer.py`

**Interfaces:**
- Consumes: `classify_response`
- Produces: `handle_raw_message(raw, post_fn) -> str`
  - `raw`：Kafka 訊息原始內容（bytes 或 str，內容是一筆事件 JSON）
  - `post_fn`：`Callable[[dict], response]`，`response` 需有 `.status_code`；送出階段的任何例外代表傳輸失敗
  - 回傳 `"ok"` / `"poison"` / `"retry"`

- [ ] **Step 1: 寫失敗測試（單元 + 整合）**

在 `tests/test_kafka_consumer.py` 末尾追加：
```python
import json

from kafka_consumer import handle_raw_message
from models import DetectEvent


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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_kafka_consumer.py -v`
Expected: FAIL，`ImportError: cannot import name 'handle_raw_message'`

- [ ] **Step 3: 寫最小實作**

在 `kafka_consumer.py` 頂部加 `import json`，並加入函式：
```python
import json


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
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_kafka_consumer.py -v`
Expected: PASS（單元 4 + 整合 2，共 10 passed）

- [ ] **Step 5: Commit**

```bash
git add kafka_consumer.py tests/test_kafka_consumer.py
git commit -m "feat: kafka consumer 的 handle_raw_message（處理單則 + 整合測試）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: 接線（post_event / build_consumer / run）+ 依賴 + 設定

**Files:**
- Modify: `kafka_consumer.py`
- Modify: `pyproject.toml`
- Modify: `.env.example`（本機 `.env` 由使用者自行補相同兩行）

**Interfaces:**
- Consumes: `handle_raw_message`、`classify_response`
- Produces:
  - `post_event(data: dict)`：用 httpx 打 `EVENTS_URL`，帶 `X-API-Key`，回傳 httpx Response
  - `build_consumer()`：回傳設定好的 `KafkaConsumer`
  - `run()`：主迴圈；`python kafka_consumer.py` 進入點

- [ ] **Step 1: 加依賴（httpx 移正式 + kafka-python-ng）**

編輯 `pyproject.toml`——把 `[project].dependencies` 補兩行、把 `[dependency-groups].dev` 的 httpx 刪掉：
```toml
[project]
dependencies = [
    "bcrypt==4.0.1",
    "boto3>=1.43.37",
    "fastapi>=0.138.1",
    "passlib[bcrypt]>=1.7.4",
    "psycopg2-binary>=2.9.12",
    "python-dotenv>=1.2.2",
    "python-jose[cryptography]>=3.5.0",
    "python-multipart>=0.0.32",
    "sqlalchemy>=2.0.51",
    "uvicorn>=0.49.0",
    "httpx>=0.28.1",
    "kafka-python-ng>=2.2.3",
]

[dependency-groups]
dev = [
    "pytest>=9.1.1",
]
```

- [ ] **Step 2: 同步並驗證可匯入**

Run: `uv sync`
接著 Run: `uv run python -c "from kafka import KafkaConsumer; import httpx; print('ok')"`
Expected: 印出 `ok`
（若 `from kafka import ...` 報錯，代表這台 Python 3.12 與該套件不合——改用 `uv remove kafka-python-ng` 後 `uv add kafka-python`，再重跑本步驟。兩者都以 `kafka` 為匯入名，程式碼不用改。）

- [ ] **Step 3: 加設定範本**

`.env.example` 末尾追加：
```bash
# Kafka consumer（kafka_consumer.py 讀取）
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
EVENTS_URL=http://localhost:8000/events
```

- [ ] **Step 4: 寫接線程式**

在 `kafka_consumer.py`：頂部匯入區補 `import logging`、`import os`、`import time`、`import httpx`；檔案末尾加入設定常數與三個函式：
```python
import logging
import os
import time

import httpx

logger = logging.getLogger("kafka_consumer")

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
EVENTS_URL = os.environ.get("EVENTS_URL", "http://localhost:8000/events")
EVENT_API_KEY = os.environ.get("EVENT_API_KEY", "")
TOPIC = "processed-reports"
GROUP_ID = "fulilian-backend"
RETRY_SLEEP_SECONDS = 5


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
        TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS.split(","),
        group_id=GROUP_ID,
        enable_auto_commit=False,   # 處理成功才手動 commit（at-least-once）
        auto_offset_reset="latest",  # 首次啟動只收「從現在開始」的新警報
        # 不設 value_deserializer：拿原始 bytes 交給 handle_raw_message 自己解析，
        # 壞 JSON 才能在函式內被接住判成 poison，而不是在迭代時噴例外
    )


def run():
    consumer = build_consumer()
    logger.info("consumer 啟動，監聽 topic=%s bootstrap=%s", TOPIC, KAFKA_BOOTSTRAP_SERVERS)
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
```

- [ ] **Step 5: 確認既有測試全綠（沒弄壞任何東西）**

Run: `uv run pytest tests/ -v`
Expected: 全部 PASS（原有測試 + 本次 test_kafka_consumer.py 的 10 個）

- [ ] **Step 6:（延後——待安裝 Docker 後再做）端到端煙霧測試**

> 前置：本步需要真的 Kafka broker，本機用 Docker 起。**尚未安裝 Docker 前跳過此步**；Step 1–5 已把邏輯用自動化測試驗證完，此步只是肉眼確認端到端跑一次。裝好 Docker Desktop 後再回來做。

1. 起 Kafka：`docker compose up -d`（用 repo 的 `docker-compose.yml`）
2. 起 web：`uv run uvicorn main:app --reload`
3. 確認本機 `.env` 已補 Step 3 那兩個變數，另一個終端機起 consumer：`uv run python kafka_consumer.py`
4. 用拋棄式假 producer 丟一筆合法訊息（albert 的正式 producer 要跑整包 AI、本機跑不動，故煙霧測試自備假訊息）。新建 `scratch_producer.py`（測完可刪）：
```python
# scratch_producer.py（拋棄式，煙霧測試用）
import json
from kafka import KafkaProducer

producer = KafkaProducer(
    bootstrap_servers="localhost:9092",
    value_serializer=lambda v: json.dumps(v).encode(),
)
producer.send("processed-reports", {
    "device_id": 1,
    "event_type": "fall",
    "clip_path": "s3://clips/smoke.mp4",
    "detected_at": "2026-07-09T10:00:00",
})
producer.flush()
print("sent")
```
執行：`uv run python scratch_producer.py`

Expected：consumer log 顯示處理成功；`GET /events` 出現該筆；前端 `/stream` 收到 `event_created`。（人工驗證，不寫成自動化測試。）

- [ ] **Step 7: Commit**

```bash
git add kafka_consumer.py pyproject.toml uv.lock .env.example
git commit -m "feat: kafka consumer 接線（run/build_consumer/post_event）+ 依賴與設定

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- 方案 B（打 HTTP）→ `post_event` + Task 2 整合測試 ✅
- 訊息契約（以真 producer 欄位為準、多餘欄位由 Pydantic 忽略）→ 整合測試用 EventCreateRequest 欄位、`POST /events` 負責忽略多餘欄位 ✅
- 錯誤處理三分類 + at-least-once（手動 commit）→ `classify_response`、`run` 的 commit 時機 ✅
- 毒訊息只 log + 保留掛勾 → `run` 內 poison 分支註解 ✅
- 函式結構分層 + 依賴注入 → Task 1/2/3 ✅
- 設定（3 個環境變數，EVENT_API_KEY 已存在）→ Task 3 Step 3 ✅
- 測試（純邏輯 + 整合）→ Task 1/2 ✅
- 動到的檔案清單 → 完全吻合 ✅
- 不在範圍（S3、event_type 對照、DLQ、方案 D）→ 未納入，正確 ✅

**Placeholder scan:** 無 TBD/TODO；每個 code step 都有完整程式碼與預期輸出。

**Type consistency:** `classify_response(status_code:int)->str`、`handle_raw_message(raw, post_fn)->str`、`post_event(data)`、`build_consumer()`、`run()` 在各 Task 命名一致；決定字串固定 `"ok"/"poison"/"retry"`。

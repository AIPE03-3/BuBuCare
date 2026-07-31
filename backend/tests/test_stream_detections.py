# test_stream_detections.py
# 即時偵測座標轉播：AI 端帶 API key 推座標，前端帶登入 token 訂閱 SSE。
#
# 這批測試的重點是**兩道門各自關得緊**——上游 albert 那版兩個端點都沒有驗證
# （POST 誰都能推假座標、GET 帶 `Access-Control-Allow-Origin: *` 誰都能看），
# 所以這裡把「沒帶憑證會被擋」當成第一等公民在測，不是附帶測一下。

import asyncio

import pytest

from core.auth import create_stream_token
from core.config import EVENT_API_KEY
from streams import detections


def frame(device_id=301, **overrides):
    body = {
        "device_id": device_id,
        "camera_id": f"Room_{device_id}_Bed",
        "persons": [{
            "bbox": [0.1, 0.2, 0.3, 0.6],
            "conf": 0.91,
            "is_fall": False,
            "track_id": 7,
            "kps": [[0.15, 0.25]] * 17,
        }],
    }
    body.update(overrides)
    return body


@pytest.fixture(autouse=True)
def clean_pool():
    """每個測試都從空的轉播池與空快取開始，免得互相污染。"""
    detections.pool.connections.clear()
    detections._latest.clear()
    yield
    detections.pool.connections.clear()
    detections._latest.clear()


# ════════════════════════════════════════════════════════
# POST /streams/detections —— AI 端推座標（API key）
# ════════════════════════════════════════════════════════

def test_push_without_api_key_is_rejected(client):
    # 沒帶 key 就想推座標 → 401。不然任何人都能往值班畫面塞假的跌倒骨架
    assert client.post("/streams/detections", json=frame()).status_code == 401


def test_push_with_wrong_api_key_is_rejected(client):
    res = client.post("/streams/detections", json=frame(),
                      headers={"X-API-Key": "not-the-key"})
    assert res.status_code == 401


def test_push_with_api_key_succeeds(client):
    res = client.post("/streams/detections", json=frame(),
                      headers={"X-API-Key": EVENT_API_KEY})
    assert res.status_code == 200
    # 沒有人在訂閱時投遞份數是 0，但推送本身仍然成功（AI 端不該因為沒人看就報錯）
    assert res.json() == {"listeners": 0}


def test_push_rejects_malformed_bbox(client):
    # bbox 必須剛好四個數字。少一個就 422，不要讓壞資料進到前端才畫爆
    res = client.post("/streams/detections", json=frame(persons=[{"bbox": [0.1, 0.2]}]),
                      headers={"X-API-Key": EVENT_API_KEY})
    assert res.status_code == 422


def test_push_caches_latest_frame_per_camera(client):
    for dev in (301, 302):
        client.post("/streams/detections", json=frame(dev),
                    headers={"X-API-Key": EVENT_API_KEY})
    # 每台鏡頭各留最後一幀，新連上的前端才有東西可以馬上畫
    assert set(detections._latest) == {301, 302}


def test_push_requires_device_id(client):
    # 前端就是靠 device_id 把座標對回鏡頭，缺了它整包沒有用處 → 422 擋掉
    body = frame(); body.pop("device_id")
    res = client.post("/streams/detections", json=body,
                      headers={"X-API-Key": EVENT_API_KEY})
    assert res.status_code == 422


# ════════════════════════════════════════════════════════
# GET /streams/detections/stream —— 前端訂閱（登入 token）
# ════════════════════════════════════════════════════════

def test_stream_without_token_is_rejected(client):
    assert client.get("/streams/detections/stream").status_code == 401


def test_stream_with_invalid_token_is_rejected(client):
    assert client.get("/streams/detections/stream?token=nope").status_code == 401


def test_stream_rejects_short_lived_stream_token(client):
    # 串流權杖（scope=stream）是給 MediaMTX 看影像用的，不該能拿來訂閱骨架座標。
    # 它會被寫進 MediaMTX 與 nginx 的存取紀錄，外流風險比登入 token 高。
    token = create_stream_token(channel="cam_in", sub="tester")
    res = client.get(f"/streams/detections/stream?token={token}")
    assert res.status_code == 401
    assert "串流權杖" in res.json()["detail"]


def test_stream_accepts_login_token(staff_token):
    # ⚠️ 刻意不開真的 SSE 連線。那是條無限長連線，TestClient 會等到心跳或逾時才回來
    #    （實測整包測試就這樣掛住不動）——`tests/test_sse.py` 對 /stream 也是同一個
    #    做法：長連線本身難在測試裡「等」，所以直接考驗證函式與轉播邏輯。
    payload = detections.require_login_token(token=staff_token)
    assert payload["sub"] == "alice"


# ════════════════════════════════════════════════════════
# 連上就先補一幀 —— 直接考組出回應內容的那兩支
# ════════════════════════════════════════════════════════

def test_replays_cached_frame_on_connect(client):
    # 先推一幀，之後才連上的前端要能立刻拿到它，不必空等下一幀
    client.post("/streams/detections", json=frame(),
                headers={"X-API-Key": EVENT_API_KEY})
    replay = detections._snapshot(None)
    assert len(replay) == 1
    chunk = detections._format(replay[0])
    assert chunk.startswith("event: detections\ndata: ")
    assert chunk.endswith("\n\n")
    assert '"device_id": 301' in chunk


def test_camera_filter_only_replays_that_camera(client):
    for dev in (301, 302):
        client.post("/streams/detections", json=frame(dev),
                    headers={"X-API-Key": EVENT_API_KEY})
    replay = detections._snapshot(302)
    assert [f["device_id"] for f in replay] == [302]


def test_replay_is_empty_when_nothing_pushed_yet():
    # 還沒有任何鏡頭推過座標時，連上不該噴錯，就是沒東西可補
    assert detections._snapshot(None) == []
    assert detections._snapshot(301) == []


# ════════════════════════════════════════════════════════
# 有界轉播池 —— 滿了要丟最舊的，不能無限長大
# ════════════════════════════════════════════════════════

def test_pool_drops_oldest_when_queue_is_full():
    """高頻座標配無界佇列＝慢速連線會把記憶體吃光，而且不會報錯。

    這是刻意不共用 events/sse.py 那個池子的原因，用測試把它釘住。
    """
    async def scenario():
        q = detections.pool.register()
        for i in range(detections.QUEUE_MAXSIZE + 5):
            detections.pool.broadcast({"device_id": 301, "seq": i})
        assert q.qsize() == detections.QUEUE_MAXSIZE, "佇列長度必須被上限擋住"
        # 留下來的是最新的那幾則，不是最舊的
        kept = [q.get_nowait()["seq"] for _ in range(detections.QUEUE_MAXSIZE)]
        assert kept == sorted(kept), "順序必須維持先進先出"
        assert kept[-1] == detections.QUEUE_MAXSIZE + 4, "最新的一則必須留著"

    asyncio.run(scenario())


def test_pool_unregister_is_idempotent():
    # 斷線與重整可能重複觸發，重複移除不能炸
    async def scenario():
        q = detections.pool.register()
        detections.pool.unregister(q)
        detections.pool.unregister(q)
        assert detections.pool.connections == []

    asyncio.run(scenario())

# 測 SSE 連線池：不開真的網路連線，直接考「信箱投遞」的邏輯
from sse import ConnectionPool, format_sse


def test_廣播_每個連線都收到():
    pool = ConnectionPool()
    q1 = pool.register()
    q2 = pool.register()

    pool.broadcast("event_created", {"event_id": "abc"})

    expected = {"event": "event_created", "data": {"event_id": "abc"}}
    assert q1.get_nowait() == expected
    assert q2.get_nowait() == expected


def test_移除連線後不再收到_其他連線不受影響():
    pool = ConnectionPool()
    q1 = pool.register()
    q2 = pool.register()

    pool.unregister(q1)  # q1 斷線
    pool.broadcast("event_created", {"x": 1})

    assert q1.empty()                          # 斷線的收不到
    assert q2.get_nowait()["data"] == {"x": 1}  # 其他人照收


def test_重複移除不報錯():
    pool = ConnectionPool()
    q = pool.register()
    pool.unregister(q)
    pool.unregister(q)  # 再移除一次，不能爆炸


def test_format_sse_輸出符合SSE格式():
    text = format_sse({"event": "event_created", "data": {"a": 1}})
    assert text == 'event: event_created\ndata: {"a": 1}\n\n'

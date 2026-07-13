# sse.py
# SSE 連線池：維護「目前所有連線的信箱（queue）」，事件進來就投遞給每個信箱
# 投遞端（處理 POST/PATCH 的程式）和收件端（/stream 的長連線迴圈）透過 queue 交接，互不等待
import asyncio
import json


class ConnectionPool:
    def __init__(self):
        # 每條 SSE 連線一個 asyncio.Queue（信箱），這個 list 就是連線池
        self.connections: list[asyncio.Queue] = []

    def register(self) -> asyncio.Queue:
        # 新連線進來：生一個信箱掛上清單
        q = asyncio.Queue()
        self.connections.append(q)
        return q

    def unregister(self, q: asyncio.Queue) -> None:
        # 連線斷了：把信箱移出清單。重複移除也不報錯（斷線和重整可能重複觸發）
        if q in self.connections:
            self.connections.remove(q)

    def broadcast(self, event_name: str, data: dict) -> None:
        # 走訪清單，往每個信箱投一份訊息副本
        # list(...) 複製一份再走訪，避免走訪途中有人 unregister 導致 list 長度變動
        message = {"event": event_name, "data": data}
        for q in list(self.connections):
            q.put_nowait(message)


# 全域單例：整個 app 共用同一個連線池（方案 A：單機記憶體，未來擴展換 Redis Pub/Sub）
pool = ConnectionPool()


def format_sse(message: dict) -> str:
    # 把內部訊息格式轉成 SSE 協定的純文字格式
    # ensure_ascii=False 讓中文直接輸出；default=str 讓 datetime 等型別自動轉字串
    data = json.dumps(message["data"], ensure_ascii=False, default=str)
    return f"event: {message['event']}\ndata: {data}\n\n"

# backend/streams/detections.py
# 即時偵測結果轉播：AI 端把每幀的人體框與骨架點推進來，前端訂閱後畫在乾淨影像上。
#
# ┌─ AI（inference_test.py）─┐   POST /streams/detections   ┌─ backend ─┐
# │ 每 N 幀送一次座標 JSON   │ ──────────────────────────>  │ 記憶體轉播 │
# └──────────────────────────┘         X-API-Key            └─────┬─────┘
#                                                                 │ SSE
# ┌─ 瀏覽器 ────────────────────────────────────────────────┐     │
# │ <video> 播 MediaMTX 的乾淨畫面 + <canvas> 疊骨架         │ <───┘
# └─────────────────────────────────────────────────────────┘
#   GET /streams/detections/stream?token=<登入 token>
#
# ## 它取代了什麼
#
# 2026-07-31 之前，前端「偵測」模式看的是 `ai/detect_publisher.py` 推的第二條影像串流：
# AI 端把框燒進畫面、再編一次 H.264 推回 MediaMTX 的 `cam_out`。那支已隨這次改動移除。
#
#   | | detect_publisher（舊，已移除）| 本檔（新）|
#   |---|---|---|
#   | 疊圖在哪 | AI 端，燒進畫面 | 瀏覽器 canvas |
#   | AI 端成本 | 每路多一支 ffmpeg 做即時編碼 | 只多一次幾 KB 的 JSON POST |
#   | 前端可否關骨架 | 不行（已經燒進去了）| 可以，按鈕切換 |
#   | 用 VLC 等外部播放器 | 看得到框 | 看不到（框不在影像裡）← 換過來的代價 |
#
# ⚠️ 資料庫的 `device.stream_channel_detect` 欄位與 `GET /devices` 的 `stream_url_detect`
#    **刻意保留但已無人使用**（前端改成在乾淨頻道上疊 canvas）。沒有一起拿掉是因為那要
#    改資料表，而欄位留著不痛不癢；要復活「第二條有框的串流」時它還在。
#
# ## 這裡刻意不共用 events/sse.py 的連線池
#
# 那個池子是給「跌倒警報」用的：低頻、**一則都不能掉**，所以 queue 無界。
# 偵測座標是相反的：每秒好幾則、**掉了就掉了**（下一幀馬上補上）。拿無界佇列
# 接高頻資料，只要有一條連線卡住（分頁切到背景、網路變慢），佇列就會一路長大到
# 吃光記憶體——而且不會報錯，只會愈來愈慢。所以這裡自己開一個**有界、滿了丟最舊**
# 的池子。丟幀對即時畫面是正確行為，排隊播放過期的骨架才是錯的。
import asyncio
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.auth import decode_access_token
from core.config import EVENT_API_KEY

router = APIRouter()

# 每條連線的信箱深度。3 幀約等於 0.3 秒的骨架，落後超過這個量的畫面本來就該丟。
QUEUE_MAXSIZE = 3
# 沒有新資料時多久送一次心跳，防中間網路設備掐斷「太久沒動靜」的長連線。
# 與 events 的 SSE 同樣是 15 秒。
HEARTBEAT_SECONDS = 15


# ════════════════════════════════════════════════════════
# 有界轉播池
# ════════════════════════════════════════════════════════
class DetectionPool:
    """每條 SSE 連線一個有界信箱；投遞時滿了就丟掉最舊的那則。"""

    def __init__(self) -> None:
        self.connections: list[asyncio.Queue] = []

    def register(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self.connections.append(q)
        return q

    def unregister(self, q: asyncio.Queue) -> None:
        if q in self.connections:
            self.connections.remove(q)

    def broadcast(self, payload: dict) -> int:
        """投遞給所有連線，回傳實際投出去的份數。

        list(...) 複製一份再走訪，避免走訪途中有人 unregister 導致長度變動。
        """
        sent = 0
        for q in list(self.connections):
            if q.full():
                # 丟最舊的那則再放新的。get_nowait 可能在多工下已被消費掉，所以要包起來。
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(payload)
                sent += 1
            except asyncio.QueueFull:
                # 極端競態下仍然滿的：直接放棄這一幀，不阻塞、不重試
                pass
        return sent


pool = DetectionPool()

# 最後一幀的快取，讓剛連上的前端不必空等下一幀才有東西畫。
# key 是 device_id，因為不同鏡頭各有各的最新畫面。
_latest: dict[int, dict] = {}


# ════════════════════════════════════════════════════════
# 契約
# ════════════════════════════════════════════════════════
class Person(BaseModel):
    """畫面裡的一個人。

    ⚠️ **座標一律是正規化到 0..1 的比例值，不是像素。** 前端的 <video> 會被 CSS
    縮放成任意大小，canvas 拿到像素座標就得先知道原始解析度才畫得對；用比例值時
    乘上當下的 canvas 寬高就好，換鏡頭、換視窗大小都不必改。
    （上游 albert 的版本在這裡自相矛盾：型別註解寫「像素座標 x1 y1 x2 y2」，
    畫的時候卻乘上畫布寬高當比例用——換一台不同解析度的鏡頭就會畫歪。）
    """
    bbox: list[float] = Field(..., min_length=4, max_length=4, description="x1,y1,x2,y2（0..1）")
    conf: float = 0.0
    is_fall: bool = False
    track_id: Optional[int] = None
    # 17 組 [x, y]（0..1）。沒偵測到的關節點是 [0, 0]，前端會跳過不畫。
    kps: Optional[list[list[float]]] = None


class DetectionFrame(BaseModel):
    # 前端就是靠這個把座標對回它清單裡的那台鏡頭（`Camera.id`）。AI 端用與 Kafka 事件
    # 完全相同的換算產生（camera_id 裡的所有數字），前端因此不必知道 "Room_301_Bed"
    # 這個字串格式——那是 AI 端的內部命名，換了不該波及前端。
    device_id: int
    # AI 端的鏡頭名，只給人看 log 用（前端不比對它）。
    camera_id: str = ""
    persons: list[Person] = []
    # AI 端的處理幀序號，除錯時對得回 log；前端不使用。
    seq: Optional[int] = None


# ── 機器驗證：AI 端帶 X-API-Key，跟 .env 的 EVENT_API_KEY 比對 ──
# 與 POST /events 同一把 key、同一套規則。刻意不另開一把：AI 端本來就已經帶著它
# 在發跌倒事件，多一把只是多一個要同步的祕密。
def require_api_key(x_api_key: Optional[str] = Header(None)) -> None:
    if not EVENT_API_KEY or x_api_key != EVENT_API_KEY:
        raise HTTPException(status_code=401, detail="API key 無效或未提供")


# ── SSE 驗證：EventSource 不能自訂 header，token 只能放網址參數 ──
# ⚠️ 這裡多做一件 events 的 /stream 沒做的事：**擋掉 scope=stream 的串流權杖**。
#    那種票是給 MediaMTX 看畫面用的、只活 60 秒，而且會被寫進 MediaMTX 與 nginx 的
#    存取紀錄。骨架座標是「畫面裡的人在哪、是不是跌倒了」，敏感度不低於影像本身，
#    要看就用登入 token（理由與 core/dependencies.get_current_user 的那段相同）。
def require_login_token(token: Optional[str] = Query(None)) -> dict:
    if not token:
        raise HTTPException(status_code=401, detail="缺少 token")
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="token 無效或過期")
    if payload.get("scope") == "stream":
        raise HTTPException(status_code=401, detail="串流權杖不可用於偵測結果訂閱")
    return payload


# ════════════════════════════════════════════════════════
# POST /streams/detections（AI 端專用，API Key 驗證）
# ════════════════════════════════════════════════════════
# async def 的原因：broadcast 走 put_nowait，要在事件迴圈執行緒上跑才安全。
@router.post("/streams/detections", dependencies=[Depends(require_api_key)])
async def push_detections(frame: DetectionFrame) -> dict[str, Any]:
    payload = frame.model_dump()
    _latest[frame.device_id] = payload
    return {"listeners": pool.broadcast(payload)}


# ════════════════════════════════════════════════════════
# GET /streams/detections/stream（需登入，token 放 query）
# ════════════════════════════════════════════════════════
@router.get("/streams/detections/stream")
async def stream_detections(
    device_id: Optional[int] = Query(None, description="只收這台鏡頭的；不給就全收"),
    current_user: dict = Depends(require_login_token),
):
    q = pool.register()

    async def generator():
        try:
            # 先把快取的最後一幀送出去，前端一連上就有東西可畫，不必空等下一幀
            for cached in _snapshot(device_id):
                yield _format(cached)
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if device_id is not None and payload.get("device_id") != device_id:
                    continue
                yield _format(payload)
        finally:
            # 瀏覽器關掉/斷線/F5 → generator 被取消 → 把信箱移出連線池
            pool.unregister(q)

    return StreamingResponse(generator(), media_type="text/event-stream", headers={
        # 中間有 nginx 代理時，沒有這兩個 header 會被緩衝住，畫面變成一頓一頓的
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


def _snapshot(device_id: Optional[int]) -> list[dict]:
    if device_id is not None:
        cached = _latest.get(device_id)
        return [cached] if cached else []
    return list(_latest.values())


def _format(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: detections\ndata: {data}\n\n"

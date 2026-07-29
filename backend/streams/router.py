# backend/streams/router.py
# 串流身分驗證。即時影像不經過後端——瀏覽器是直接連 MediaMTX 拿畫面的，
# 所以登入驗證管不到它。這裡補上的機制是：
#
#   ① 前端拿登入 token 來換一張 60 秒的串流權杖（POST /streams/{channel}/token）
#   ② 前端帶著權杖去連 MediaMTX
#   ③ MediaMTX 回頭打後端問「這張權杖有效嗎」（POST /streams/auth，Task 2 實作）
#
# 兩個端點的呼叫者不同：①是瀏覽器（需登入），③是 MediaMTX（沒有帳號，必須公開）。
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

# import 模組而非常數：值在 import 當下就綁定，直接 import 常數會讓測試 patch 不到
# （devices/router.py 當初就是為了同一個理由這樣寫）
from core import config
from core.auth import create_stream_token, decode_access_token
from core.dependencies import get_current_user

router = APIRouter()


# ════════════════════════════════════════════════════════
# POST /streams/{channel}/token（需登入）：換一張串流權杖
# ════════════════════════════════════════════════════════
# channel 是頻道名（cam_in / phone_a…），不是完整網址。
# 刻意不查資料庫確認頻道存在：MediaMTX 的 paths 沒宣告的頻道本來就連不上，
# 多一層檢查擋不到額外的東西，卻要為此多一次查詢。
@router.post("/streams/{channel}/token")
def issue_stream_token(
    channel: str,
    current_user: dict = Depends(get_current_user),
):
    return {
        "token": create_stream_token(channel=channel, sub=current_user["sub"]),
        # 一併回傳壽命，前端不必自己猜幾秒後要重新換票
        "expires_in": config.STREAM_TOKEN_EXPIRE_SECONDS,
    }


# ── MediaMTX 打來的請求格式 ──────────────────────────────
# ⚠ 除了 action，每個欄位都必須可為 None：MediaMTX 有些欄位會送 null 而不是空字串，
#   型別寫死成 str 會讓 Pydantic 直接回 422。MediaMTX 收到 422（不是 401 也不是 204）
#   的行為未定義，整套驗證會失效。
class MediaMTXAuthRequest(BaseModel):
    action: str                        # read（觀看）/ publish（推流）/ api / metrics / pprof
    path: str | None = None            # 頻道名，例如 cam_in
    protocol: str | None = None        # webrtc / rtsp / rtmp / hls / srt
    token: str | None = None           # Authorization: Bearer 的內容，瀏覽器帶的串流權杖
    user: str | None = None            # 網址內嵌的帳號，AI 端走 RTSP 時帶
    password: str | None = None
    ip: str | None = None
    id: str | None = None
    query: str | None = None
    userAgent: str | None = None       # MediaMTX 用駝峰式命名，這裡照抄不改


# ════════════════════════════════════════════════════════
# POST /streams/auth（公開）：MediaMTX 問「這個人能不能看？」
# ════════════════════════════════════════════════════════
# 必須公開：呼叫者是 MediaMTX，它沒有帳號、不會登入。
# 安全性來自「沒有有效憑證就一定 401」，不是來自「誰能呼叫這個端點」——
# 外人打進來最多只能得知「某張票有效與否」，問不出其他東西。
#
# 回 204 = 放行、401 = 擋下，這是 MediaMTX 規定的格式。
@router.post("/streams/auth", status_code=204)
def authorize_mediamtx(body: MediaMTXAuthRequest):
    # ── 分支①：RTSP 讀取一律放行（AI 端走這條）──
    # 必須排在驗票之前，否則會被分支②的「必須是 webrtc」擋掉。
    # ⚠ 刻意放行：代價是同網段用 VLC 就看得到，換 AI 端不必改網址。
    #    瀏覽器那條（分支②）不受影響，仍需權杖。
    if body.protocol == "rtsp" and body.action == "read":
        return

    # ── 分支②：其餘一律驗短命權杖（瀏覽器走這條）──
    payload = decode_access_token(body.token or "")
    allowed = (
        payload is not None                     # 簽名是我們的、而且沒過期（JWT 函式庫負責）
        and payload.get("scope") == "stream"    # 是串流權杖，不是登入 token
        and payload.get("path") == body.path    # 票綁死頻道，拿去看別的頻道無效
        and body.action == "read"               # 觀看票不能拿來推流
        and body.protocol == "webrtc"           # 權杖只走瀏覽器這條路
    )
    if not allowed:
        raise HTTPException(status_code=401, detail="串流權杖無效")

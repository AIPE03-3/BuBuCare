# backend/streams/router.py
# 串流身分驗證。即時影像不經過後端——瀏覽器是直接連 MediaMTX 拿畫面的，
# 所以登入驗證管不到它。這裡補上的機制是：
#
#   ① 前端拿登入 token 來換一張 60 秒的串流權杖（POST /streams/{channel}/token）
#   ② 前端帶著權杖去連 MediaMTX
#   ③ MediaMTX 回頭打後端問「這張權杖有效嗎」（POST /streams/auth，Task 2 實作）
#
# 兩個端點的呼叫者不同：①是瀏覽器（需登入），③是 MediaMTX（沒有帳號，必須公開）。
from fastapi import APIRouter, Depends

from core.auth import create_stream_token
from core.config import STREAM_TOKEN_EXPIRE_SECONDS
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
        "expires_in": STREAM_TOKEN_EXPIRE_SECONDS,
    }

from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError

from backend.core.config import (
    SECRET_KEY,
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_DAYS,
    STREAM_TOKEN_EXPIRE_SECONDS,
)
# SECRET_KEY：簽名用的密鑰（從 .env 來）
# ALGORITHM：簽名演算法　ACCESS_TOKEN_EXPIRE_DAYS：token 有效天數

# ---------------------------------------------
# 把資料包進 token 裡，簽名產出一串 token 字串
# ---------------------------------------------
def create_access_token(data: dict):
    # 接收一個字典，通常是 {"sub": "alice"}（sub = subject，代表使用者）

    to_encode = data.copy() # 複製一份字典，避免修改到原本傳進來的 data

    expire = datetime.now(timezone.utc) + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS) # 取得現在的 UTC 時間 + 1 天的時間長度 → 「明天此刻」的時間點，作為到期時間
    
    to_encode.update({"exp": expire})
    # update() 是把新的 key-value 塞進字典
    # "exp" 是 JWT 規定的標準欄位名稱，表示 expiration
    # 變成 {"sub": "alice", "exp": 明天此刻}

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_stream_token(camera_path: str, sub: str) -> str:
    """建立只可讀取單一 MediaMTX path 的短效 JWT。"""
    expire = datetime.now(timezone.utc) + timedelta(seconds=STREAM_TOKEN_EXPIRE_SECONDS)
    payload = {
        "sub": sub,
        "scope": "stream",
        "path": camera_path,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    # jwt.encode(資料, 密鑰, algorithm=演算法) → 把字典加簽名，產出 token 字串

# ---------------------------------------------
# 把 token 拆開來看，如果是合法、沒過期的 token，回傳裡面的資料；如果是假的或過期的，回傳 None
# ---------------------------------------------
def decode_access_token(token: str): # 接收一個 token 字串
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM]) # 解開 token，algorithms=[list]因為解碼時可以接受多種演算法
        return payload # 把解出來的資料回傳給呼叫者
    except JWTError:
        return None
    

'''
整體流程總結
登入成功
  → create_access_token({"sub": "alice"})
  → 回傳 token 給前端

之後每次請求
  → 前端把 token 放在 Header 送來
  → decode_access_token(token)
  → 有效 → 知道是 alice，放行
  → 無效 → 回傳 401 未授權
'''

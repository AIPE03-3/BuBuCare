from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError

from core.config import (
    SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_HOURS, STREAM_TOKEN_EXPIRE_SECONDS,
)
# SECRET_KEY：簽名用的密鑰（從 .env 來）
# ALGORITHM：簽名演算法　ACCESS_TOKEN_EXPIRE_HOURS：登入 token 有效時數（8）
# STREAM_TOKEN_EXPIRE_SECONDS：串流權杖有效秒數（預設 60）

# ---------------------------------------------
# 把資料包進 token 裡，簽名產出一串 token 字串
# ---------------------------------------------
def create_access_token(data: dict):
    # 接收一個字典，通常是 {"sub": "alice"}（sub = subject，代表使用者）

    to_encode = data.copy() # 複製一份字典，避免修改到原本傳進來的 data

    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS) # 現在的 UTC 時間 + 8 小時（約一個班次）＝到期時間
    
    to_encode.update({"exp": expire})
    # update() 是把新的 key-value 塞進字典
    # "exp" 是 JWT 規定的標準欄位名稱，表示 expiration
    # 變成 {"sub": "alice", "exp": 明天此刻}

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    # jwt.encode(資料, 密鑰, algorithm=演算法) → 把字典加簽名，產出 token 字串

# ---------------------------------------------
# 簽一張串流權杖：只能看指定的一個頻道，60 秒後作廢
# ---------------------------------------------
# 跟 create_access_token 放同一個檔案，是因為兩者用「同一把 SECRET_KEY」簽名——
# 光看 token 外觀分不出是登入用還是串流用，所以才需要 scope 這個欄位當記號。
# 兩邊門口都要檢查：驗票時沒有 scope=stream 就擋（防止拿一整天有效的登入 token 來看畫面）、
# get_current_user 看到 scope=stream 也要擋（防止拿串流權杖去呼叫一般 API）。
def create_stream_token(channel: str, sub: str):
    expire = datetime.now(timezone.utc) + timedelta(seconds=STREAM_TOKEN_EXPIRE_SECONDS)
    to_encode = {
        "sub": sub,          # 誰要看（員編），出事查得到
        "scope": "stream",   # 「僅限串流」的記號
        "path": channel,     # 綁死哪一個頻道，拿去看別的頻道無效
        "exp": expire,
    }
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


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
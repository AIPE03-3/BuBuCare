from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer # FastAPI 內建的工具，負責從 HTTP 請求的 Header 裡自動抓出 token
from backend.core.auth import decode_access_token


# 告訴 FastAPI「token 要從 /login 這個路由拿」，同時讓 /docs 測試頁面自動顯示登入框
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


def get_current_user(token: str = Depends(oauth2_scheme)):
    # Depends(oauth2_scheme)：自動從請求 Header 抓出 token 字串，不用手動解析
    payload = decode_access_token(token)
    if payload is None:
        # raise：主動拋出錯誤(401：未授權)，程式不會繼續往下執行
        raise HTTPException(status_code=401, detail="token 無效或過期")
    # token 合法就回傳使用者資料，例如 {"sub": "alice", "role": "admin"}
    return payload


def require_admin(user: dict = Depends(get_current_user)):
    # Depends(get_current_user)：依賴串聯，先完成 token 驗證再繼續
    # dict.get("role")：安全讀取欄位，沒有這個 key 也不會出錯（回傳 None）
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="權限不足") # 403：「有登入但沒有權限」
    return user

'''
依賴注入串聯示意:

路由收到請求 (路由舉例:/admin/delete-user)
  → Depends(oauth2_scheme)    抓出 Header 的 token 字串
  → Depends(get_current_user) 驗證 token，拿到 user
  → Depends(require_admin)    確認 role == "admin"
  → 才執行路由本體

任何一層失敗就直接回傳錯誤，後面的程式碼完全不會執行。
'''
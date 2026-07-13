from fastapi import FastAPI, Depends, HTTPException 
# 建立 app 本體, 依賴注入, 回傳 HTTP 錯誤給前端（例如 401、404）
from fastapi.middleware.cors import CORSMiddleware 
# 允許瀏覽器從其他網址呼叫這個 API（開發測試用）

from fastapi.security import OAuth2PasswordRequestForm
# 這是 FastAPI 內建的登入表單格式
# 前端送來的 username + password 會被自動解析成這個物件

from sqlalchemy.orm import Session
from pydantic import BaseModel # 定義「前端送來的 JSON 長什麼樣子」，FastAPI 會自動驗證格式

import os
from datetime import datetime, timezone

from backend.core.database import Base, engine, get_db
from backend.core.models import User
from backend.core.security import verify_password, hash_password
from backend.core.auth import create_access_token
from backend.core.dependencies import get_current_user, require_admin
from backend.events.router import router as event_router


# ── 定義「POST /register 收到的 JSON 格式」────────────────
# 前端送來 {"username": "alice", "password": "1234"}
# FastAPI 會自動比對這個格式
class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str


# 程式啟動時建立所有還不存在的資料表（表名見 models.py，例如 user_account）
# CI／測試環境設 SKIP_DB_INIT=1 時跳過：避免 import 當下就去連正式資料庫
# （雲端測試機連不到 AWS RDS，這行會卡住或報錯）
if os.getenv("SKIP_DB_INIT") != "1":
    Base.metadata.create_all(bind=engine)

# ── 建立 FastAPI app 本體 ─────────────────────────────────
# 這個 app 物件就是整個服務的核心
# 所有路由都掛在它身上（@app.post、@app.get...）
app = FastAPI()

# 告訴瀏覽器：「哪些網站可以存取我的 API。」
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 事件相關路由（POST /events、SSE、判定/結案）都在 event_routes.py
app.include_router(event_router)


# ════════════════════════════════════════════════════════
# 路由一：POST /register（公開，不需要登入）
# ════════════════════════════════════════════════════════
@app.post("/register")
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    # body        → FastAPI 自動把前端送來的 JSON 解析成 RegisterRequest 物件
    # Depends(get_db) → 執行這個函式前，先幫我開一個資料庫連線，用完自動關

    # 查資料庫有沒有同名帳號
    existing = db.query(User).filter(User.name == body.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="帳號已存在")

    new_user = User(
        name=body.username,
        password=hash_password(body.password),  # 密碼雜湊後才存，不存明文
        email=body.email,
        role="staff"
    )
    db.add(new_user)
    db.commit()
    return {"message": f"帳號 {body.username} 建立成功"}


# ════════════════════════════════════════════════════════
# 路由二：POST /login（公開，不需要登入）
# ════════════════════════════════════════════════════════
@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # OAuth2...Form → FastAPI 自動從 form body 抓 username、password

    # 到資料庫查有沒有這個帳號
    user = db.query(User).filter(User.name == form_data.username).first()

    # 帳號不存在，或密碼比對失敗 → 回傳 401
    if not user or not verify_password(form_data.password, user.password):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")

    # 登入成功 → 記下這次登入時間（UTC），存回資料庫
    user.last_login_time = datetime.now(timezone.utc)
    db.commit()

    # 驗證通過 → 產生 JWT token，把帳號名稱和角色包進去
    # 之後每次請求帶著這個 token，伺服器就知道你是誰
    access_token = create_access_token(data={"sub": user.name, "role": user.role})

    # 回傳 token 給前端，前端要把它存起來，之後每次請求放在 Header 裡
    return {"access_token": access_token, "token_type": "bearer"}


# ════════════════════════════════════════════════════════
# 路由三：GET /me（需要登入）
# ════════════════════════════════════════════════════════
@app.get("/me")
def read_me(current_user: dict = Depends(get_current_user)):
    # Depends(get_current_user) → 執行這個路由前，先去 dependencies.py 驗證 token
    #   token 合法 → current_user 是解出來的資料，例如 {"sub": "alice", "role": "staff"}
    #   token 無效 → 直接回 401，這個函式根本不會被執行
    #
    # 這就是 FastAPI + JWT 的核心：
    #   路由本身不管驗證邏輯，驗證交給 Depends，通過了才進來
    return {"username": current_user["sub"], "role": current_user["role"]}


# ════════════════════════════════════════════════════════
# 路由四：DELETE /users/{user_id}（需要登入 + 需要 admin 角色）
# ════════════════════════════════════════════════════════
@app.delete("/users/{user_id}")
def delete_user(user_id: int, current_user: dict = Depends(require_admin), db: Session = Depends(get_db)):
    # {user_id} → URL 路徑參數，FastAPI 自動抓出來並確認是整數
    # Depends(require_admin) → 先驗證 token，再確認 role == "admin"，兩關都過才進來

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="找不到使用者")
    db.delete(user)
    db.commit()
    return {"message": f"已刪除使用者 {user_id}"}

# backend/users/router.py
# 帳號相關的所有路由（註冊/登入/查自己/刪帳號）。用 APIRouter 分檔，main.py 只負責組裝 app。

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
# OAuth2PasswordRequestForm 是 FastAPI 內建的登入表單格式
# 前端送來的 username + password 會被自動解析成這個物件
from pydantic import BaseModel, Field  # 定義「前端送來的 JSON 長什麼樣子」，FastAPI 會自動驗證格式
from sqlalchemy.orm import Session

from backend.core.auth import create_access_token
from backend.core.database import get_db
from backend.core.dependencies import get_current_user, require_admin
from backend.core.models import User
from backend.core.security import verify_password, hash_password

router = APIRouter()


# ── 定義「POST /register 收到的 JSON 格式」────────────────
# 前端送來 {"employee_id": "E100", "full_name": "新同事", "password": "..."}
# FastAPI 會自動比對這個格式
class RegisterRequest(BaseModel):
    employee_id: str
    full_name: str
    password: str = Field(min_length=6)   # admin 給的臨時密碼，最低 6 碼
    role: Literal["staff", "admin"] = "staff"  # 只收這兩種值，其他直接 422
    email: str | None = None              # 改選填：不再是找回密碼的管道


# ════════════════════════════════════════════════════════
# 路由一：POST /register（admin-only：員編是人資編號，只有 admin 能開帳號）
# ════════════════════════════════════════════════════════
@router.post("/register", status_code=201)
def register(body: RegisterRequest,
             current_user: dict = Depends(require_admin),
             db: Session = Depends(get_db)):
    if db.query(User).filter(User.employee_id == body.employee_id).first():
        raise HTTPException(status_code=400, detail="員編已存在")
    # email 沒填（None）不查重——資料庫允許多筆 NULL；有填才需要擋重複
    if body.email and db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=400, detail="email 已被使用")

    new_user = User(
        employee_id=body.employee_id,
        full_name=body.full_name,
        password=hash_password(body.password),  # 密碼雜湊後才存，不存明文
        email=body.email,
        role=body.role,
        # must_change_password 不用指定：模型預設 True，逼新帳號首次登入改密碼
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)  # 讓資料庫回填自動編號的 id
    return {"id": new_user.id, "employee_id": new_user.employee_id,
            "full_name": new_user.full_name, "role": new_user.role}


# ════════════════════════════════════════════════════════
# 路由二：POST /login（公開，不需要登入）
# ════════════════════════════════════════════════════════
@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # OAuth2...Form → FastAPI 自動從 form body 抓 username、password

    # 到資料庫查有沒有這個帳號
    user = db.query(User).filter(User.employee_id == form_data.username).first()

    # 帳號不存在，或密碼比對失敗 → 回傳 401
    if not user or not verify_password(form_data.password, user.password):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")

    # 登入成功 → 記下這次登入時間（UTC），存回資料庫
    user.last_login_time = datetime.now(timezone.utc)
    db.commit()

    # 驗證通過 → 產生 JWT token，把員編、姓名和角色包進去
    # 之後每次請求帶著這個 token，伺服器就知道你是誰
    access_token = create_access_token(
        data={"sub": user.employee_id, "full_name": user.full_name, "role": user.role})

    # 回傳 token 給前端，前端要把它存起來，之後每次請求放在 Header 裡
    return {"access_token": access_token, "token_type": "bearer"}


# ════════════════════════════════════════════════════════
# 路由三：GET /me（需要登入）
# ════════════════════════════════════════════════════════
@router.get("/me")
def read_me(current_user: dict = Depends(get_current_user)):
    # Depends(get_current_user) → 執行這個路由前，先去 dependencies.py 驗證 token
    #   token 合法 → current_user 是解出來的資料，例如 {"sub": "alice", "full_name": "愛麗絲", "role": "staff"}
    #   token 無效 → 直接回 401，這個函式根本不會被執行
    #
    # 這就是 FastAPI + JWT 的核心：
    #   路由本身不管驗證邏輯，驗證交給 Depends，通過了才進來
    # current_user 是解出來的 JWT payload，三個欄位都在裡面，不用查資料庫
    return {
        "employee_id": current_user["sub"],
        "full_name": current_user["full_name"],
        "role": current_user["role"],
    }


# ════════════════════════════════════════════════════════
# 路由四：DELETE /users/{user_id}（需要登入 + 需要 admin 角色）
# ════════════════════════════════════════════════════════
@router.delete("/users/{user_id}")
def delete_user(user_id: int, current_user: dict = Depends(require_admin), db: Session = Depends(get_db)):
    # {user_id} → URL 路徑參數，FastAPI 自動抓出來並確認是整數
    # Depends(require_admin) → 先驗證 token，再確認 role == "admin"，兩關都過才進來

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="找不到使用者")
    db.delete(user)
    db.commit()
    return {"message": f"已刪除使用者 {user_id}"}

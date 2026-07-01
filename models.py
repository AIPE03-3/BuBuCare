# models.py
from typing import Optional
from datetime import datetime
from sqlalchemy import Integer, String, DateTime
from sqlalchemy.orm import mapped_column, Mapped  # 新版 SQLAlchemy 的欄位寫法，可以標記型別
from database import Base

class User(Base):  # 對應資料庫裡的 user_account 表
    __tablename__ = "user_account"

    # Mapped[int] 告訴 Python「這個欄位是整數」，autoincrement=True 表示 id 自動從 1 累加
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Mapped[str] 告訴 Python「這個欄位是字串」，String(100) 限制最多 100 個字元
    # nullable=False 表示這個欄位不能是空的，一定要有值
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    # String(255) 給密碼雜湊值足夠空間（bcrypt 結果大約 60 字元，255 是安全上限）
    password: Mapped[str] = mapped_column(String(255), nullable=False)

    # email 也不能重複，每個帳號一個 email
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    # default="staff" 表示新帳號預設是一般員工，除非明確指定 admin
    role: Mapped[str] = mapped_column(String(50), default="staff")

    # Optional 表示這個欄位可以是空的（新帳號還沒登入過，沒有紀錄）
    last_login_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
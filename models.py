# models.py
from sqlalchemy import Column, Integer, String
from database import Base

class User(Base):  # 定義資料庫裡有一張表叫 users
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True) # 每個使用者的編號，自動產生，不會重複
    username = Column(String, unique=True, index=True) # 帳號名稱
    hashed_password = Column(String) # 存「加密過的密碼」，不是使用者輸入的原始密碼
    role = Column(String, default="staff")  # "admin" 或 "staff"，對應你們討論的兩級權限
    
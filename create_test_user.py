from database import SessionLocal, Base, engine
from models import User
from security import hash_password

# 確保資料表存在（第一次執行時會自動建立）
Base.metadata.create_all(bind=engine)

db = SessionLocal()

# 要建立的初始帳號清單
accounts = [
    {
        "name": "admin",
        "password": hash_password("123456"),
        "email": "admin@fulilian.com",
        "role": "admin",
    },
    {
        "name": "staff01",
        "password": hash_password("123456"),
        "email": "staff01@fulilian.com",
        "role": "staff",
    },
]

for account in accounts:
    existing = db.query(User).filter(User.name == account["name"]).first()
    if existing:
        print(f"帳號 {account['name']} 已存在，略過建立")
    else:
        db.add(User(**account))
        db.commit()
        print(f"帳號建立完成：{account['name']} / 123456（role: {account['role']}）")

db.close()

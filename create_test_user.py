from database import SessionLocal, Base, engine
from models import User
from security import hash_password

Base.metadata.create_all(bind=engine)

db = SessionLocal()

existing = db.query(User).filter(User.username == "admin").first()
if existing:
    print("帳號已存在，略過建立")
else:
    test_user = User(
        username="admin",
        hashed_password=hash_password("123456"),
        role="admin"
    )
    db.add(test_user)
    db.commit()
    print("測試帳號建立完成：admin / 123456")

db.close()
# conftest.py
# pytest 的共用設定檔，所有測試檔都會自動讀到這裡的 fixtures，不需要 import

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from database import Base, get_db
from models import User
from security import hash_password

# 建立一個「只存在記憶體」的測試資料庫，不會動到真正的 fulilian.db
# StaticPool：讓所有連線共用同一個 connection，這樣 CREATE TABLE 和 INSERT 才看得到彼此
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    # 把 FastAPI 原本連到 fulilian.db 的行為，換成連到測試記憶體資料庫
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# 把 app 的 get_db 依賴注入換掉，讓所有 API 路由在測試時都使用測試資料庫
app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
def client():
    # 回傳一個可以對 FastAPI app 發送請求的測試客戶端
    return TestClient(app)


@pytest.fixture
def db_session():
    # 讓測試可以直接查詢測試資料庫（例如查出某個使用者的 ID）
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_database():
    # autouse=True：每個測試前自動執行，不需要在測試函式裡手動呼叫
    # 建立所有資料表
    Base.metadata.create_all(bind=engine)

    # 塞入測試用的初始帳號
    db = TestingSessionLocal()
    db.add(User(username="alice", hashed_password=hash_password("secret123"), role="staff"))
    db.add(User(username="boss", hashed_password=hash_password("adminpass"), role="admin"))
    db.commit()
    db.close()

    yield  # 測試在這裡執行

    # 測試結束後清掉所有資料表，確保每次測試都是乾淨的狀態
    Base.metadata.drop_all(bind=engine)

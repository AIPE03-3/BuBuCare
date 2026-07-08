# conftest.py
# pytest 的共用設定檔，所有測試檔都會自動讀到這裡的 fixtures，不需要 import

import os
import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# 測試用的機器驗證 key，要在 import main 之前設好（event 端點會從環境變數讀）
os.environ["EVENT_API_KEY"] = "test-api-key"

from main import app
from database import Base, get_db
from models import User, Company, Location, Device, Staff, DetectEvent
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

    # 塞入測試用的初始資料：公司 → 裝置/照護員 → 帳號
    db = TestingSessionLocal()
    db.add(Company(company_id=1, company_name="測試安養院"))
    db.commit()  # 先 commit 公司，後面的 FK 才掛得上

    db.add(Location(location_id=1, location_name="交誼廳", company_id=1))
    db.add(Device(device_id=1, device_name="交誼廳-01", location_id=1,
                  status="active", company_id=1))
    db.add(Staff(staff_id=1, staff_name="小美", company_id=1))
    db.add(Staff(staff_id=2, staff_name="阿強", company_id=1))
    db.add(User(name="alice", password=hash_password("secret123"), email="alice@test.com", role="staff"))
    db.add(User(name="boss", password=hash_password("adminpass"), email="boss@test.com", role="admin"))
    db.commit()
    db.close()

    yield  # 測試在這裡執行

    # 測試結束後清掉所有資料表，確保每次測試都是乾淨的狀態
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def staff_token(client):
    # 用種子帳號 alice 登入，拿一顆真的 JWT token
    res = client.post("/login", data={"username": "alice", "password": "secret123"})
    return res.json()["access_token"]


@pytest.fixture
def auth_headers(staff_token):
    # 大多數測試用的登入 header
    return {"Authorization": f"Bearer {staff_token}"}


@pytest.fixture
def make_event(db_session):
    # 事件工廠：測試想要什麼狀態的事件，直接在 DB 裡造一筆
    def _make(**kwargs):
        defaults = dict(
            device_id=1,
            location_id=1,  # 比照真實路徑：事件建立時從裝置凍一份位置（裝置 1 在 location 1）
            event_type="fall",
            clip_path="s3://clips/test.mp4",
            detected_at=datetime(2026, 7, 2, 14, 30),
            company_id=1,
        )
        defaults.update(kwargs)
        event = DetectEvent(**defaults)
        db_session.add(event)
        db_session.commit()
        db_session.refresh(event)
        return event
    return _make


@pytest.fixture
def session_factory():
    # 背景任務測試用：回傳測試記憶體 DB 的 session 工廠
    # （watch_delivery 會用它開自己的 session，不能連到正式 DB）
    return TestingSessionLocal

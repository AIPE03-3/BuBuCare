# 測資料模型：新表能建立、預設值正確、種子資料有進去
from datetime import datetime
from backend.core.models import Company, Location, Device, Staff, DetectEvent, User


def test_建立事件_預設狀態是pending(db_session):
    event = DetectEvent(
        device_id=1,
        event_type="fall",
        clip_path="s3://clips/e1.mp4",
        detected_at=datetime(2026, 7, 2, 14, 30),
        company_id=1,
    )
    db_session.add(event)
    db_session.commit()
    db_session.refresh(event)

    assert event.event_id  # UUID 字串自動產生
    assert event.status == "pending"   # 後端預設，不靠外部指定
    assert event.verdict is None       # 還沒人判定
    assert event.verdict_by is None    # 還沒人按判定（Task 1 新增）
    assert event.resolved_by is None   # 還沒人按結案（Task 1 新增）
    assert event.staff_id is None      # 舊欄位，Task 4 移除


def test_種子資料存在(db_session):
    assert db_session.query(Company).count() == 1
    device = db_session.query(Device).filter_by(device_id=1).first()
    assert device.device_name == "交誼廳-01"
    # relationship：透過 device.location_id 自動查 locations 表拿名稱
    assert device.location.location_name == "交誼廳"
    assert db_session.query(Staff).count() == 2


def test_既有帳號自動掛預設公司(db_session):
    alice = db_session.query(User).filter_by(employee_id="alice").first()
    assert alice.company_id == 1

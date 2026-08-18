# 測資料模型：新表能建立、預設值正確、種子資料有進去
from datetime import datetime
from core.models import Company, Location, Device, Staff, DetectEvent, User


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


def test_detect_event_report_roundtrip(db_session, make_event):
    # 通報單：form 整包 JSON 存進去，讀回來還是 dict、內容不變
    from core.models import DetectEventReport
    from datetime import datetime

    event = make_event()
    report = DetectEventReport(
        event_id=event.event_id,
        report_type="initial",
        form={"caseName": "王小明", "reportType": "初報", "handling": ["送醫治療"]},
        created_by="alice",
        created_at=datetime(2026, 7, 20, 10, 0),
    )
    db_session.add(report)
    db_session.commit()
    db_session.refresh(report)

    assert report.report_id == 1                      # 自動編號 PK
    assert report.form["caseName"] == "王小明"        # JSON 欄位讀寫是 dict
    assert report.form["handling"] == ["送醫治療"]    # 巢狀結構原樣保存

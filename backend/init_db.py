"""初始化正式資料庫（PostgreSQL）：建表 → 種 demo 資料 → 建初始帳號。

可重複執行：已存在的一律略過，不會報錯。
新環境（組員的機器、驗收主機、未來部署）第一次跑這支就能讓事件流程動起來。

用法（先 cd backend）：
    python -m init_db
"""
from core.database import SessionLocal, Base, engine
from core.models import Company, Location, Device, Staff, User
from core.security import hash_password


def create_tables():
    """建立 models.py 定義的所有表（已存在的不動）。"""
    Base.metadata.create_all(bind=engine)
    print("表建立完成（已存在的不動）")


def seed_demo_data(db):
    """種入系統跑起來的最低內容物：公司 / 區域 / 裝置 / 照護員。

    沒有這些資料，POST /events 會因為查不到 device_id 而回 400，整個事件流程一步都跑不動。
    """
    if db.query(Company).filter_by(company_id=1).first() is None:
        db.add(Company(company_id=1, company_name="扶力憐示範安養院"))
        db.commit()
        print("已建立預設公司（id=1）")
    else:
        print("預設公司已存在，略過")

    if db.query(Location).first() is None:
        db.add(Location(location_name="交誼廳", company_id=1))
        db.add(Location(location_name="走廊", company_id=1))
        db.commit()
        print("已建立區域 2 筆")
    else:
        print("區域已存在，略過")

    if db.query(Device).first() is None:
        # 查出剛種的區域編號，裝置掛上對應的 location_id
        loc_ids = {l.location_name: l.location_id for l in db.query(Location).all()}
        db.add(Device(device_name="交誼廳-01", location_id=loc_ids.get("交誼廳"), status="active", company_id=1))
        db.add(Device(device_name="走廊-01", location_id=loc_ids.get("走廊"), status="active", company_id=1))
        db.commit()
        print("已建立示範裝置 2 台")
    else:
        print("裝置已存在，略過")

    # 邊緣 AI 端（inference_test.py）以相機房號當 device_id：Room_301_Bed -> 301、302、303。
    # 後端裝置表要有對應 device_id，POST /events 才不會因查無裝置回 400（見上方 line 23 註解）。
    # 逐 id 冪等新增（不套上面「有任何裝置就整批略過」的 guard），可安全重跑、不動既有 1/2/101。
    for _dev_id in (301, 302, 303):
        if db.query(Device).filter_by(device_id=_dev_id).first() is None:
            db.add(Device(device_id=_dev_id, device_name=f"寢室-{_dev_id}",
                          status="active", company_id=1))
    db.commit()
    print("已確保邊緣相機裝置 301/302/303 存在")

    if db.query(Staff).first() is None:
        db.add(Staff(staff_name="照護員A", company_id=1))
        db.add(Staff(staff_name="照護員B", company_id=1))
        db.commit()
        print("已建立照護員 2 名")
    else:
        print("照護員已存在，略過")


def seed_accounts(db):
    """建立可以登入中控站的初始帳號（A001 管理員 / E001 陳雅文，密碼皆 123456）。

    密碼一定要經過 bcrypt 雜湊才能存，所以不能直接用 SQL INSERT 明文。
    種子帳號手動設 must_change_password=False，登入時不會被要求改密碼。
    """
    accounts = [
        {"employee_id": "A001", "full_name": "系統管理員",
         "email": "a001@fulilian.com", "role": "admin"},
        {"employee_id": "E001", "full_name": "陳雅文",
         "email": "e001@fulilian.com", "role": "staff"},
    ]
    for account in accounts:
        if db.query(User).filter(User.employee_id == account["employee_id"]).first():
            print(f"帳號 {account['employee_id']} 已存在，略過建立")
        else:
            db.add(User(**account, password=hash_password("123456"),
                        must_change_password=False))
            db.commit()
            print(f"帳號建立完成：{account['employee_id']} / 123456（role: {account['role']}）")


if __name__ == "__main__":
    create_tables()

    db = SessionLocal()
    try:
        seed_demo_data(db)
        seed_accounts(db)
    finally:
        db.close()

    print("初始化完成")

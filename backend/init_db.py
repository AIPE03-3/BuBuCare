"""初始化正式資料庫（PostgreSQL）：建表 → 補舊表欄位 → 種 demo 資料 → 建初始帳號。

可重複執行：已存在的一律略過，不會報錯。
新環境（組員的機器、驗收主機、未來部署）第一次跑這支就能讓事件流程動起來。

用法：
    python -m backend.init_db
"""
from sqlalchemy import text

from backend.core.database import SessionLocal, Base, engine
from backend.core.models import Company, Location, Device, Staff, User
from backend.core.security import hash_password


def create_tables():
    """建立 models.py 定義的所有表（已存在的不動）。"""
    Base.metadata.create_all(bind=engine)
    print("表建立完成（已存在的不動）")


def run_column_migrations():
    """補齊「舊表」缺的欄位——歷史遺留，全新資料庫上是空轉。

    這幾個欄位（company_id / floor / location_id / notified_at）都是功能做到一半才加的。
    當初正式 DB 的表已經建好了，create_all 不會回頭改既有的表，只好手寫 ALTER TABLE 補。

    現在 models.py 已完整定義這些欄位，所以：
      - 全新的 DB：上面 create_tables() 建表時就含這些欄位，這裡的 IF NOT EXISTS 不會做事
      - 現有的正式 DB：欄位早就補完了，一樣不會做事
    留著只是為了保護「還沒升級的舊 DB」（例如組員手上的）。等確認大家的 DB 都升級後可整段刪除。
    """
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE user_account "
            "ADD COLUMN IF NOT EXISTS company_id INT NOT NULL DEFAULT 1"
        ))
        conn.execute(text(
            "ALTER TABLE locations "
            "ADD COLUMN IF NOT EXISTS floor VARCHAR(10)"
        ))
        conn.execute(text(
            "ALTER TABLE detect_events "
            "ADD COLUMN IF NOT EXISTS location_id INT REFERENCES locations(location_id)"
        ))
        conn.execute(text(
            "ALTER TABLE detect_events "
            "ADD COLUMN IF NOT EXISTS notified_at TIMESTAMP"
        ))
    print("舊表欄位補齊完成（已存在則略過）")


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

    if db.query(Staff).first() is None:
        db.add(Staff(staff_name="照護員A", company_id=1))
        db.add(Staff(staff_name="照護員B", company_id=1))
        db.commit()
        print("已建立照護員 2 名")
    else:
        print("照護員已存在，略過")


def seed_accounts(db):
    """建立可以登入中控站的初始帳號（admin / staff01，密碼皆 123456）。

    密碼一定要經過 bcrypt 雜湊才能存，所以不能直接用 SQL INSERT 明文。
    """
    accounts = [
        {"name": "admin", "email": "admin@fulilian.com", "role": "admin"},
        {"name": "staff01", "email": "staff01@fulilian.com", "role": "staff"},
    ]
    for account in accounts:
        if db.query(User).filter(User.name == account["name"]).first():
            print(f"帳號 {account['name']} 已存在，略過建立")
        else:
            db.add(User(**account, password=hash_password("123456")))
            db.commit()
            print(f"帳號建立完成：{account['name']} / 123456（role: {account['role']}）")


if __name__ == "__main__":
    create_tables()
    run_column_migrations()

    db = SessionLocal()
    try:
        seed_demo_data(db)
        seed_accounts(db)
    finally:
        db.close()

    print("初始化完成")

# create_seed_data.py
# 把正式 PostgreSQL 升級到最新狀態：建新表 + user_account 加欄位 + 種初始資料
# 可重複執行：已有的自動略過，不會報錯（跟 create_test_user.py 同風格）
from sqlalchemy import text
from database import SessionLocal, Base, engine
import models  # noqa: F401  讓 Base 認得所有表，create_all 才會建

Base.metadata.create_all(bind=engine)  # 建立還不存在的表（已存在的不動）
print("新表建立完成（已存在的不動）")

# 幫既有的 user_account 表加 company_id 欄位
# NOT NULL DEFAULT 1 → 加欄位的當下，舊帳號自動回填 1（預設公司）
# IF NOT EXISTS → 第二次執行直接略過
with engine.begin() as conn:
    conn.execute(text(
        "ALTER TABLE user_account "
        "ADD COLUMN IF NOT EXISTS company_id INT NOT NULL DEFAULT 1"
    ))
print("user_account.company_id 欄位完成（已存在則略過）")

from models import Company, Location, Device, Staff  # noqa: E402

db = SessionLocal()

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

db.close()
print("種子資料完成")

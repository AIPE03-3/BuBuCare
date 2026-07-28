# models.py
import uuid
from typing import Optional
from datetime import datetime
from sqlalchemy import Integer, String, DateTime, Float, Text, ForeignKey, Enum, Boolean, JSON
from sqlalchemy.orm import mapped_column, Mapped, relationship  # 新版 SQLAlchemy 的欄位寫法，可以標記型別
from core.database import Base

class User(Base):  # 對應資料庫裡的 user_account 表
    __tablename__ = "user_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 登入用的員工編號（機構既有人資編號），取代原本使用者自取的 name
    employee_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    # 真實姓名，顯示用
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # String(255) 給密碼雜湊值足夠空間（bcrypt 結果大約 60 字元）
    password: Mapped[str] = mapped_column(String(255), nullable=False)

    # 不再是找回密碼的管道，改選填；有填仍不可重複
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)

    # 固定選項欄位比照 status/verdict/severity 慣例：
    # PostgreSQL 真 ENUM、SQLite 用 CHECK 約束擋非法值
    role: Mapped[str] = mapped_column(
        Enum("staff", "admin", name="user_role", create_constraint=True),
        default="staff", nullable=False,
    )

    # admin 開的新帳號預設要求首次登入改密碼；種子帳號由種子腳本設 False
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # 軟刪除：停用帳號設 False，不真的刪資料（員編不可重用，資料留著可回溯）
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # 可以是空的（新帳號還沒登入過）
    last_login_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 所屬機構。default=1 表示新帳號自動掛預設公司，多租戶邏輯未來才做
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.company_id"), nullable=False, default=1
    )


class Company(Base):  # 安養院（多租戶預留，本輪只有一筆預設公司 id=1）
    __tablename__ = "companies"

    company_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)


class Location(Base):  # 區域（交誼廳、走廊…）：獨立成表讓名稱統一，只被 devices 引用、不連 events
    __tablename__ = "locations"

    location_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    location_name: Mapped[str] = mapped_column(String(50), nullable=False)
    floor: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"), nullable=False)


class Device(Base):  # 攝影機裝置
    __tablename__ = "devices"

    device_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # location_id 和 stream_url 是 spec 裡唯二可空的欄位：裝置剛建檔時可能還沒定位置、還沒接串流
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("locations.location_id"), nullable=True)
    # Enum：固定選項的欄位。PostgreSQL 建真 ENUM 型別，DB 層直接擋壞值
    # create_constraint=True：讓沒有原生 ENUM 的資料庫（如測試用的 SQLite）補上 CHECK 約束，行為跟正式環境一樣嚴格
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive", "fault", name="device_status", create_constraint=True),
        nullable=False, default="active"
    )
    stream_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"), nullable=False)

    # 關聯屬性：程式可直接寫 device.location.location_name，SQLAlchemy 依 location_id 自動查
    location: Mapped[Optional["Location"]] = relationship("Location")


class Staff(Base):
    __tablename__ = "staff"

    staff_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    staff_name: Mapped[str] = mapped_column(String(50), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"), nullable=False)


class DetectEvent(Base):  # 跌倒事件主表
    __tablename__ = "detect_events"

    # UUID 存成 36 字元字串，SQLite（測試）和 PostgreSQL（正式）都通用
    event_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.device_id"), nullable=False)
    # 事件發生當下所在區域，寫入時從裝置抄一份凍住，之後裝置搬走也不動（保護歷史紀錄）
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("locations.location_id"), nullable=True)
    event_type: Mapped[Optional[str]] = mapped_column(String(50))  # 例如 fall

    # 拆兩欄的狀態機：status 管進度，verdict 管人工判定結果
    # 程式端讀寫都還是普通字串（例如 "pending"），Enum 只是讓資料庫多一層守門
    status: Mapped[str] = mapped_column(
        Enum("pending", "in_progress", "resolved", name="event_status", create_constraint=True),
        nullable=False, default="pending"
    )
    verdict: Mapped[Optional[str]] = mapped_column(
        Enum("true_alarm", "false_alarm", name="event_verdict", create_constraint=True), nullable=True
    )

    # 事件影像片段。可空是為了 hazard（潛在危險）：那是「桌上有把刀」這種持續狀態，
    # 沒有「事發前後 N 秒」可錄，只有快照。跌倒/滑落仍強制要有，由 service 層把關
    # （見 handle_incoming_event）——DB 放寬到 nullable，業務規則寫在服務層。
    clip_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    snapshot_path: Mapped[Optional[str]] = mapped_column(String(255))    # 截圖
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # 前端第一次回報收到（ack）的時間；NULL = 尚未收到，重推機制據此判斷要不要補推
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # 誰點的誰負責：兩欄都存 user_account 的員編（JWT 的 sub），不是 staff 表的數字 id
    verdict_by: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("user_account.employee_id"), nullable=True
    )  # 判定者：按下 verdict 的人；真跌倒、誤報都記
    resolved_by: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("user_account.employee_id"), nullable=True
    )  # 結案者：按下 resolve 的人；誤報一鍵結案時與 verdict_by 同人
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"), nullable=False, default=1)

    yolo_score: Mapped[Optional[float]] = mapped_column(Float)      # 該事件 YOLO 打的分數
    vlm_summary: Mapped[Optional[str]] = mapped_column(Text)        # VLM 情境描述

    # 潛在危險（event_type="hazard"）偵測到的物品，存 COCO class name 原字串（knife/scissors）。
    # 不存中文：顯示文字是前端的事（前端 HAZARD_OBJECT_LABEL 負責翻譯），三層傳同一個 key。
    # 跌倒事件為 NULL。不做 Enum 是因為值域會隨模型重訓長出新類別，不該每次都動 DB 型別。
    hazard_object: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # 顯示事件位置走這個關聯（凍住的 location_id），不要繞去 device.location（那是裝置現況）
    location: Mapped[Optional["Location"]] = relationship("Location")

    # 該事件的所有通報單，舊→新排序（取最後一筆即最新通報階段）
    reports: Mapped[list["DetectEventReport"]] = relationship(
        "DetectEventReport", order_by="DetectEventReport.created_at"
    )


class DetectEventReport(Base):  # 事件通報單：每次儲存獨立一筆（初報/續報/結報累積，不覆蓋）
    __tablename__ = "detect_event_reports"

    report_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("detect_events.event_id"), nullable=False
    )
    # 初報/續報/結報。抽出成欄是因為要獨立查詢；其餘表單內容不查、整包存 form
    report_type: Mapped[str] = mapped_column(
        Enum("initial", "follow_up", "final", name="report_type", create_constraint=True),
        nullable=False,
    )
    # 表單整包 JSON 保管：定義權在前端（政府制式表單），表單改版後端零修改
    form: Mapped[dict] = mapped_column(JSON, nullable=False)
    # 誰存的誰負責：從 JWT 的 sub 記員編，前端不帶（同 verdict_by/resolved_by 模式）
    created_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("user_account.employee_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

# models.py
import uuid
from typing import Optional
from datetime import datetime
from sqlalchemy import Integer, String, DateTime, Float, Text, ForeignKey, Enum
from sqlalchemy.orm import mapped_column, Mapped, relationship  # 新版 SQLAlchemy 的欄位寫法，可以標記型別
from database import Base

class User(Base):  # 對應資料庫裡的 user_account 表
    __tablename__ = "user_account"

    # Mapped[int] 告訴 Python「這個欄位是整數」，autoincrement=True 表示 id 自動從 1 累加
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Mapped[str] 告訴 Python「這個欄位是字串」，String(100) 限制最多 100 個字元
    # nullable=False 表示這個欄位不能是空的，一定要有值
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    # String(255) 給密碼雜湊值足夠空間（bcrypt 結果大約 60 字元，255 是安全上限）
    password: Mapped[str] = mapped_column(String(255), nullable=False)

    # email 也不能重複，每個帳號一個 email
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    # default="staff" 表示新帳號預設是一般員工，除非明確指定 admin
    role: Mapped[str] = mapped_column(String(50), default="staff")

    # Optional 表示這個欄位可以是空的（新帳號還沒登入過，沒有紀錄）
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


class Staff(Base):  # 照護員：被指派去現場處理的人（跟 user_account 的登入帳號是兩回事）
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

    clip_path: Mapped[str] = mapped_column(String(255), nullable=False)  # 事件影像片段
    snapshot_path: Mapped[Optional[str]] = mapped_column(String(255))    # 截圖
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    staff_id: Mapped[Optional[int]] = mapped_column(ForeignKey("staff.staff_id"), nullable=True)  # 判真跌倒時指派
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"), nullable=False, default=1)

    yolo_score: Mapped[Optional[float]] = mapped_column(Float)      # 該事件 YOLO 打的分數
    yolo_threshold: Mapped[Optional[float]] = mapped_column(Float)  # 當時的門檻值（門檻日後會調，回訓分析要知道）
    vlm_summary: Mapped[Optional[str]] = mapped_column(Text)        # VLM 情境描述
    vlm_confidence: Mapped[Optional[float]] = mapped_column(Float)
    recommended_action: Mapped[Optional[str]] = mapped_column(String(255))
    incident_draft_notification: Mapped[Optional[str]] = mapped_column(String(255))
    severity: Mapped[Optional[str]] = mapped_column(
        Enum("low", "medium", "high", name="event_severity", create_constraint=True)
    )

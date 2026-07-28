# backend/devices/router.py
# 裝置（鏡頭）相關路由。前端「鏡頭清單」頁面的資料來源
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core import config  # import 模組而非常數：讓測試能用 monkeypatch 換掉 MEDIAMTX_BASE_URL
from core.database import get_db
from core.dependencies import get_current_user, require_admin
from core.models import Device, Location

router = APIRouter()


def whep_url(channel: str | None) -> str | None:
    """把資料庫裡的頻道名，接上 .env 的 MediaMTX 位址，組成瀏覽器可用的 WHEP 網址。

    頻道名對齊 AI 端命名：cam_in（進 AI 前的原味）／cam_out（AI 畫框後）。
    傑雅版原本叫 my_camera_tapo，語意等同 cam_in；改名理由是 cam_in/cam_out 描述的是
    「在 AI 的哪一端」，換攝影機廠牌也不會過期。

    位址或頻道名任一為空 → 回 None，代表「這個環境沒有這條串流」，前端據此退回占位框。
    """
    if not config.MEDIAMTX_BASE_URL or not channel:
        return None
    return f"{config.MEDIAMTX_BASE_URL.rstrip('/')}/{channel}/whep"


def serialize_device(device: Device) -> dict:
    # 裝置的統一 JSON 結構：位置資訊 JOIN 好夾帶，前端不用再查
    # status 回後端字彙（active/inactive/fault），前端在他們的 api 層對照成 online/offline/disabled
    #
    # 串流刻意回兩種形式，因為兩邊消費者要的協定不同：
    #   stream_channel* = 原始頻道名，給 AI 端（ffmpeg/OpenCV 走 rtsp://<自己的MediaMTX>:8554/<頻道名>）
    #   stream_url*     = 組好的 WHEP 網址，給瀏覽器（只看得懂 WebRTC，讀不了 RTSP）
    # 資料庫只存頻道名、主機位址各端自己接，搬機器就不必改資料庫。
    return {
        "device_id": device.device_id,
        "device_name": device.device_name,
        "location": device.location.location_name if device.location else None,
        "floor": device.location.floor if device.location else None,
        "stream_channel": device.stream_channel,
        "stream_channel_detect": device.stream_channel_detect,
        "stream_url": whep_url(device.stream_channel),
        "stream_url_detect": whep_url(device.stream_channel_detect),
        "status": device.status,
    }


# ════════════════════════════════════════════════════════
# GET /devices（登入即可）：全部裝置清單
# ════════════════════════════════════════════════════════
@router.get("/devices")
def list_devices(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    devices = db.query(Device).order_by(Device.device_id).all()
    return [serialize_device(d) for d in devices]


# ── POST /devices 收到的 JSON 格式 ──
# stream_url 是接真實攝影機的入口，格式如 rtsp://<帳號>:<密碼>@<IP>:554/stream2，
# 所以長度上限貼齊 DB 的 String(255)：超長在這裡就回 422，不要讓它掉到資料庫變 500。
# device_id 開放指定：邊緣 AI 端以「房號」當 device_id（Room_301_Bed -> 301，見
# ai/inference_test.py 的解析），註冊真攝影機時要能對齊房號，不能只吃資料庫自動編號。
# company_id 不收：目前單一機構，固定 1（模型 nullable=False 且無預設，一定要給值）。
class DeviceCreateRequest(BaseModel):
    device_name: str = Field(min_length=1, max_length=255)
    stream_url: str | None = Field(default=None, max_length=255)
    status: Literal["active", "inactive", "fault"] = "active"
    location_id: int | None = None
    device_id: int | None = None


# ════════════════════════════════════════════════════════
# POST /devices（需 admin）：新增鏡頭
# ════════════════════════════════════════════════════════
@router.post("/devices", status_code=201)
def create_device(
    body: DeviceCreateRequest,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if body.device_id is not None and \
            db.query(Device).filter(Device.device_id == body.device_id).first():
        raise HTTPException(status_code=400, detail="裝置編號已存在")

    if body.location_id is not None and \
            db.query(Location).filter(Location.location_id == body.location_id).first() is None:
        raise HTTPException(status_code=400, detail="區域不存在")

    # device_id 用「有給才放進 kwargs」，不直接傳 None：明確傳 None 會把 NULL 塞進 PK 欄位，
    # PostgreSQL 的 SERIAL 不會補預設值，直接 IntegrityError 變成 500。
    fields = {
        "device_name": body.device_name,
        "stream_url": body.stream_url,
        "status": body.status,
        "location_id": body.location_id,
        "company_id": 1,
    }
    if body.device_id is not None:
        fields["device_id"] = body.device_id

    device = Device(**fields)
    db.add(device)
    db.commit()
    db.refresh(device)
    return serialize_device(device)


# ── PATCH /devices/{device_id} 收到的 JSON 格式 ──
# 只收 device_name：location/floor 是 locations 表的欄位，從裝置端點改會波及
# 同區域所有裝置與歷史事件的顯示位置（location_id 凍結設計），區域管理是獨立功能
class DeviceRenameRequest(BaseModel):
    device_name: str = Field(min_length=1)


# ════════════════════════════════════════════════════════
# PATCH /devices/{device_id}（需 admin）：改鏡頭名稱
# ════════════════════════════════════════════════════════
@router.patch("/devices/{device_id}")
def rename_device(
    device_id: int,
    body: DeviceRenameRequest,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if device is None:
        raise HTTPException(status_code=404, detail="裝置不存在")

    device.device_name = body.device_name
    db.commit()
    db.refresh(device)
    return serialize_device(device)

# backend/devices/router.py
# 裝置（鏡頭）相關路由。前端「鏡頭清單」頁面的資料來源
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.database import get_db
from core.dependencies import get_current_user, require_admin
from core.models import Device

router = APIRouter()


def serialize_device(device: Device) -> dict:
    # 裝置的統一 JSON 結構：位置資訊 JOIN 好夾帶，前端不用再查
    # status 回後端字彙（active/inactive/fault），前端在他們的 api 層對照成 online/offline/disabled
    return {
        "device_id": device.device_id,
        "device_name": device.device_name,
        "location": device.location.location_name if device.location else None,
        "floor": device.location.floor if device.location else None,
        "stream_url": device.stream_url,
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

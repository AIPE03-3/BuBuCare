# backend/devices/router.py
# 裝置（鏡頭）相關路由。前端「鏡頭清單」頁面的資料來源
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.dependencies import get_current_user
from backend.core.models import Device

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

# backend/reports/router.py
# 通報單路由：存（POST）與查（GET）。表單整包 JSON 保管，定義權在前端
# 設計規格：backend/docs/superpowers/specs/2026-07-20-frontend-gap-endpoints-design.md
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.dependencies import get_current_user
from backend.core.models import DetectEvent, DetectEventReport

router = APIRouter()


def serialize_report(report: DetectEventReport) -> dict:
    return {
        "report_id": report.report_id,
        "event_id": report.event_id,
        "report_type": report.report_type,
        "form": report.form,
        "created_by": report.created_by,
        "created_at": report.created_at.isoformat(),
    }


def get_event_or_404(db: Session, event_id: str) -> DetectEvent:
    event = db.query(DetectEvent).filter(DetectEvent.event_id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="事件不存在")
    return event


# ── POST /events/{event_id}/reports 收到的 JSON 格式 ──
# form 不驗內容：表單定義權在前端，後端只保管；report_type 用 Literal 擋非法值
class ReportCreateRequest(BaseModel):
    report_type: Literal["initial", "follow_up", "final"]
    form: dict


# ════════════════════════════════════════════════════════
# POST /events/{event_id}/reports（登入即可）：存一筆通報單
# ════════════════════════════════════════════════════════
@router.post("/events/{event_id}/reports", status_code=201)
def create_report(
    event_id: str,
    body: ReportCreateRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_event_or_404(db, event_id)

    report = DetectEventReport(
        event_id=event_id,
        report_type=body.report_type,
        form=body.form,
        created_by=current_user["sub"],  # 誰存的誰負責，從 JWT 記
        created_at=datetime.now(),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return serialize_report(report)


# ════════════════════════════════════════════════════════
# GET /events/{event_id}/reports（登入即可）：查某事件全部通報單
# ════════════════════════════════════════════════════════
@router.get("/events/{event_id}/reports")
def list_reports(
    event_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_event_or_404(db, event_id)

    # 排序契約：舊→新（初報→續報→結報的歷程順序）。
    # 前端 getLatestReport 取陣列最後一筆當最新，這個順序不能反。
    # 同一秒存兩筆時用 report_id（自動編號）決勝，保證順序穩定
    reports = (
        db.query(DetectEventReport)
        .filter(DetectEventReport.event_id == event_id)
        .order_by(DetectEventReport.created_at.asc(), DetectEventReport.report_id.asc())
        .all()
    )
    return [serialize_report(r) for r in reports]

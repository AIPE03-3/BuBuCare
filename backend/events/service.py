# backend/events/service.py
# 事件「處理」核心：存 DB + 廣播。跟「入口」（POST /events、未來的 Kafka consumer）拆開，
# Kafka 接上時直接呼叫 handle_incoming_event()，這裡零改動
import asyncio

from sqlalchemy.orm import Session

from core.database import SessionLocal
from core.models import DetectEvent, Device, User
from events.sse import pool


class DeviceNotFoundError(Exception):
    # 事件指到不存在的裝置。入口層自己決定怎麼回應（HTTP 入口回 400）
    pass


def serialize_event(
    event: DetectEvent,
    device: Device,
    verdict_by_name: str | None = None,
    resolved_by_name: str | None = None,
) -> dict:
    # 事件的統一 JSON 結構：SSE 廣播和 GET /events 都用這一個函式，
    # 前端只需寫一套顯示邏輯。裝置名稱/位置直接夾帶，前端不用再查。
    #
    # 處理人顯示名（verdict_by_name / resolved_by_name）跟 device 一樣「由呼叫端事先查好再傳進來」，
    # 本函式只負責組裝、不碰資料庫：列表端用 JOIN 一次撈、單筆端用 operator_names() 取（見下方）。
    #
    # ⚠ event.reports 會觸發延遲載入（多發一次 SQL）。一次序列化多筆事件時，
    #   查詢端要先 selectinload(DetectEvent.reports)，否則每筆各查一次（N+1）
    latest_report = event.reports[-1] if event.reports else None

    return {
        "event_id": event.event_id,
        "device_id": event.device_id,
        "device_name": device.device_name,
        # 讀事件凍住的位置（event.location），不看裝置現況；事件沒凍到位置時回 None
        "location": event.location.location_name if event.location else None,
        "event_type": event.event_type,
        "status": event.status,
        "verdict": event.verdict,
        "clip_path": event.clip_path,
        "snapshot_path": event.snapshot_path,
        "detected_at": event.detected_at.isoformat(),
        # 讓前端/除錯看得到送達狀態：None = 還沒被 ack
        "notified_at": event.notified_at.isoformat() if event.notified_at else None,
        "verdict_by": event.verdict_by,
        "verdict_by_name": verdict_by_name,
        "resolved_by": event.resolved_by,
        "resolved_by_name": resolved_by_name,
        # 通報階段＝最新一筆通報單的類型；兩者皆 None 代表這個事件還沒有任何通報單
        "report_stage": latest_report.report_type if latest_report else None,
        "last_report_at": latest_report.created_at.isoformat() if latest_report else None,
        "company_id": event.company_id,
        "yolo_score": event.yolo_score,
        "vlm_summary": event.vlm_summary,
        # agent P2：AI 建議判斷，僅供人工複判參考，null 代表 AI 未給出建議（含舊事件）
        "ai_verdict": event.ai_verdict,
        "ai_confidence": event.ai_confidence,
        "ai_reasoning": event.ai_reasoning,
    }


def operator_names(db: Session, event: DetectEvent) -> tuple[str | None, str | None]:
    # 依單筆 event 的 verdict_by / resolved_by 員編，查 user_account 的 full_name。
    # 給「只動一筆事件」的呼叫端用（判定 / 結案）；列表端自己用 JOIN 一次撈好、不走這裡。
    # 回傳 (判定者名, 結案者名)，查不到的為 None（前端會自動退回顯示員編）。
    ids = {eid for eid in (event.verdict_by, event.resolved_by) if eid}
    if not ids:
        return None, None
    names = dict(
        db.query(User.employee_id, User.full_name)
        .filter(User.employee_id.in_(ids))
        .all()
    )
    return names.get(event.verdict_by), names.get(event.resolved_by)


def is_delivered(db: Session, event_id: str) -> bool:
    # 重推的停止判斷。三種情況都算「不用再推」：
    #   1. notified_at 有值 → 前端已回報收到
    #   2. status 離開 pending → 有人已在處理，等於也送達了
    #   3. 事件不存在 → 已被刪或查無，沒東西可推
    event = db.query(DetectEvent).filter(DetectEvent.event_id == event_id).first()
    if event is None:
        return True
    if event.notified_at is not None:
        return True
    if event.status != "pending":
        return True
    return False


def rebroadcast_event(db: Session, event_id: str) -> None:
    # 重推：重查事件與裝置，沿用 event_created 事件名再廣播一次
    # （前端以 event_id 去重，收到同一筆只會更新該列、不會重複顯示）
    event = db.query(DetectEvent).filter(DetectEvent.event_id == event_id).first()
    if event is None:
        return
    device = db.query(Device).filter(Device.device_id == event.device_id).first()
    pool.broadcast("event_created", serialize_event(event, device))


async def watch_delivery(
    event_id: str,
    *,
    session_factory=SessionLocal,
    interval: float = 10.0,
    max_attempts: int = 3,
) -> None:
    # 事件建立後盯送達：每 interval 秒檢查一次，未送達就重推一次，最多 max_attempts 次
    # session_factory 可注入：正式用 SessionLocal，測試傳測試 DB 的工廠
    for _ in range(max_attempts):
        await asyncio.sleep(interval)
        db = session_factory()  # 背景任務不在請求裡，要開自己的 session
        try:
            if is_delivered(db, event_id):
                return
            rebroadcast_event(db, event_id)
        finally:
            db.close()


# 同一起事件補寫時，只准覆寫這幾欄。
#
# 為什麼要限制：補寫是事發約 35 秒後才到的（VLM 判讀要跑那麼久），那時護理師很可能
# 已經按過「接手處理」或「誤報」。整包覆蓋會把人工操作洗掉——畫面上事件退回待處理，
# 值班人員會以為自己剛才按的沒生效。所以 status / verdict / notified_at / clip_path /
# snapshot_path 一律不碰，補寫只補「AI 說了什麼」。
ENRICHABLE_FIELDS = ("vlm_summary", "ai_verdict", "ai_confidence", "ai_reasoning")


def find_same_event(db: Session, data: dict) -> DetectEvent | None:
    """找出「同一起事件」的既有紀錄，沒有就回 None。

    認定條件是 device_id + detected_at + event_type 三個一組。這不是新發明的鍵：
    agent 自己的冪等去重用的就是這三個（agent/nodes/publish.py 的 dedupe_key），
    而邊緣端補寫那封訊息的 detected_at 與第一封逐字相同（ai/inference_test.py 的
    route_by_confidence 兩封共用同一個值）。
    """
    return (
        db.query(DetectEvent)
        .filter(
            DetectEvent.device_id == data["device_id"],
            DetectEvent.detected_at == data["detected_at"],
            DetectEvent.event_type == data.get("event_type"),
        )
        .first()
    )


def handle_incoming_event(db: Session, data: dict) -> tuple[dict, bool]:
    """收一則事件訊息：同一起事件就補寫，否則新增。回傳 (payload, 是不是新建的)。

    2026-08-05 加上「補寫」這條路。原因：高信心跌倒走快速道、依規格不等 VLM
    （docs/ARCHITECTURE.md §2「危急事件零延遲」），所以它的 vlm_summary 一直是邊緣端
    寫死的罐頭字串。要讓前端警示視窗有真的 AI 判讀，就得讓 agent 事後把判讀文字補回
    **同一筆**事件——不補的話，那封訊息會變成事件中心多一筆一模一樣的跌倒。

    回傳值 2026-08-05 從單一 dict 改成 (dict, created)：入口層要靠它決定回 201 還是 200、
    以及要不要啟動 watch_delivery（那是盯「新事件有沒有送到護理師眼前」用的，補寫不需要）。
    """
    # 1. 先確認裝置存在（不存在就什麼都不做）
    device = db.query(Device).filter(Device.device_id == data["device_id"]).first()
    if device is None:
        raise DeviceNotFoundError(f"裝置 {data['device_id']} 不存在")

    # 2. 同一起事件已經在庫裡 → 補寫既有那筆，不新增
    existing = find_same_event(db, data)
    if existing is not None:
        for field in ENRICHABLE_FIELDS:
            # 只有「這次真的帶了值」才覆蓋：補寫訊息沒帶到的欄位，保留原本的值，
            # 不要被 None 洗掉（例如 agent 判不出 verdict 時 ai_verdict 是 None）
            if data.get(field) is not None:
                setattr(existing, field, data[field])
        db.commit()
        db.refresh(existing)
        payload = serialize_event(existing, device)
        # event_updated 而非 event_created：前端據此就地更新既有那筆（含還開著的警示視窗），
        # 不會再跳一次全螢幕警示（EventsProvider 以 event_id upsert）
        pool.broadcast("event_updated", payload)
        return payload, False

    # 3. 新事件：照舊存 DB（status 一律後端設 pending，company_id / location_id 都跟著
    #    裝置當下狀態凍一份）
    event = DetectEvent(**data, company_id=device.company_id, location_id=device.location_id)
    db.add(event)
    db.commit()
    db.refresh(event)

    # 4. 存成功才廣播（資料庫是唯一真相；存失敗上面就丟例外，不會走到這行）
    payload = serialize_event(event, device)
    pool.broadcast("event_created", payload)
    return payload, True

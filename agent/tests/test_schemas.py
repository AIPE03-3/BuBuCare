# agent/tests/test_schemas.py
# 驗收重點（WBS P0.4）：03-contracts.md 的範例訊息通過驗證；壞資料丟明確錯誤；
# Kafka 2 輸出是現有格式的超集（舊 consumer 不改也能跑）。

import pytest
from pydantic import ValidationError

from agent.schemas import AlertMessage, ALDecision, JudgeResult, ProcessedReport

# ⚠️ 以下兩則是從邊緣端「程式碼」抄來的真實訊息，不是文件範例。
# 03-contracts.md §1 的範例與實際送出的格式不符（缺 device_id、camera_id 也對不上），
# 照文件寫 schema 會讓 100% 的真實訊息驗證失敗進 DLQ。

# ai/inference_test.py:341 慢車道告警（注意：完全沒有 camera_id 欄位）
REAL_FALL_ALERT = {
    "device_id": 301,
    "event_type": "fall",
    "clip_path": "test_demo/test1.mp4",
    "detected_at": "2026-07-19T15:30:00",
    "snapshot_path": "/abs/path/snapshot_Room_301_Bed_20260719_153000.jpg",
    "image_filename": "snapshot_Room_301_Bed_20260719_153000.jpg",
    "yolo_score": 0.72,
    "yolo_threshold": 0.45,   # 慢車道保留：AI 內部欄位，judge prompt 比大小用
    "vlm_summary": "【AI 信心度不足】已觸發大模型二審…",
}

# ai/modules/sanity_check.py:35 定時巡檢（camera_id 是非數字字串、且沒有 yolo_threshold）
REAL_ROUTINE_ALERT = {
    "alert_id": "RTN_Room_301_Bed_1753000000",
    "device_id": 301,
    "event_type": "Routine_Environment_Sanity_Check",
    "detected_at": "2026-07-19T15:30:00",
    "camera_id": "Room_301_Bed",
    "yolo_score": 1.0,
    "image_filename": "snapshot_Room_301_Bed_20260719_153000.jpg",
    "severity": "low",
    "status": "PENDING_VLM_ROUTE",
}


# ── AlertMessage：真實邊緣端訊息 ─────────────────────────
def test_真實跌倒告警可通過驗證():
    alert = AlertMessage(**REAL_FALL_ALERT)

    assert alert.device_id == 301          # 直接讀邊緣端算好的 device_id
    assert alert.event_type == "fall"
    assert alert.yolo_threshold == 0.45
    assert alert.is_routine_check is False


def test_真實巡檢訊息可通過驗證():
    alert = AlertMessage(**REAL_ROUTINE_ALERT)

    assert alert.device_id == 301
    assert alert.camera_id == "Room_301_Bed"
    assert alert.yolo_threshold == 0.5     # 巡檢不送這個欄位，用預設值
    assert alert.is_routine_check is True


def test_邊緣端多送的欄位被忽略而非報錯():
    # snapshot_path / vlm_summary / alert_id / status / severity（巡檢模組仍在送）
    # 都不是我們要的，但它們的存在不該讓訊息被拒絕
    assert AlertMessage(**REAL_FALL_ALERT).device_id == 301
    assert AlertMessage(**REAL_ROUTINE_ALERT).device_id == 301


# ── device_id 的解析順序 ────────────────────────────────
def test_優先採用邊緣端算好的_device_id():
    # 兩個都有時以 device_id 為準：它是邊緣端真正拿來標示裝置的欄位
    alert = AlertMessage(event_type="fall", device_id=301, camera_id="Room_999_Bed")

    assert alert.device_id == 301


def test_沒有_device_id_時從_camera_id_抽數字():
    # 抽法與邊緣端一致（inference_test.py:299 / sanity_check.py:31）
    alert = AlertMessage(event_type="fall", camera_id="Room_301_Bed")

    assert alert.device_id == 301


def test_camera_id_是純數字也可以():
    assert AlertMessage(event_type="fall", camera_id="101").device_id == 101
    assert AlertMessage(event_type="fall", camera_id=101).device_id == 101


def test_兩個欄位都給不出裝置時驗證失敗():
    # 不硬塞假 device_id（舊 vlm_worker 會 fallback 成寫死的 101，把事件記到別台裝置）
    with pytest.raises(ValidationError):
        AlertMessage(event_type="fall", camera_id="no_digits_here")
    with pytest.raises(ValidationError):
        AlertMessage(event_type="fall")


def test_可選欄位缺席不會壞():
    alert = AlertMessage(event_type="fall", device_id=101)

    assert alert.detected_at is None
    assert alert.clip_path is None
    assert alert.yolo_score == 0.0
    assert alert.camera_label == "101"     # 沒有 camera_id 就用裝置編號當標籤


# ── ProcessedReport（Kafka 2 出）─────────────────────────
LEGACY_FIELDS = {
    "device_id": 101,
    "event_type": "Fall_Detected",
    "clip_path": "/vids/fallback.mp4",
    "detected_at": "2026-07-19T15:30:00",
    "snapshot_path": "/data/snapshots/snapshot_101_20260719_153000.jpg",
    "yolo_score": 0.72,
    "vlm_summary": "【安養中心緊急通報】…",
}


def test_只有舊欄位就能組出訊息():
    # Never break userspace：新欄位全部 optional
    report = ProcessedReport(**LEGACY_FIELDS)

    assert report.ai_verdict is None
    assert report.ai_confidence is None


def test_訊息不帶通報單草稿():
    # 已拍板：草稿改為前端開表單時即時產生，不走 Kafka（03-contracts.md §5）
    assert "report_draft" not in ProcessedReport(**LEGACY_FIELDS).model_dump()


def test_輸出是現有格式的超集():
    # 舊欄位一個不動、一個不少：backend/kafka_consumer.py 不改也能跑
    payload = ProcessedReport(**LEGACY_FIELDS).model_dump()

    for key, value in LEGACY_FIELDS.items():
        assert payload[key] == value, f"既有欄位 {key} 的語意被改掉了"


def test_新欄位可帶_ai_建議():
    report = ProcessedReport(
        **LEGACY_FIELDS,
        ai_verdict="true_alarm",
        ai_confidence=0.87,
        ai_reasoning="VLM 確認人員倒臥於床邊地面",
    )

    assert report.ai_verdict == "true_alarm"
    assert report.ai_confidence == 0.87


def test_uncertain_不會出現在對外欄位():
    # 契約規定：判不出來一律降級為 ai_verdict=null（交回人工），不對外送 uncertain
    with pytest.raises(ValidationError):
        ProcessedReport(**LEGACY_FIELDS, ai_verdict="uncertain")


def test_不再送出後端已移除的欄位():
    # severity / yolo_threshold 已於 2026-07-19（1bbb585）從後端整組移除，
    # 送過去只會被 Pydantic 靜默丟掉；yolo_threshold 仍留在 Kafka 1 供 judge prompt 用
    payload = ProcessedReport(**LEGACY_FIELDS).model_dump()

    assert "severity" not in payload
    assert "yolo_threshold" not in payload


# ── 節點 structured output ──────────────────────────────
def test_judge_結果的三個欄位():
    result = JudgeResult(verdict="true_alarm", confidence=0.9, reasoning="姿態與跌倒相符")

    assert result.verdict == "true_alarm"


def test_judge_接受_uncertain():
    # Agent 內部允許 uncertain，只是不對外送（由 publish 降級成 null）
    assert JudgeResult(
        verdict="uncertain", confidence=0.4, reasoning="畫面遮蔽"
    ).verdict == "uncertain"


@pytest.mark.parametrize("bad_confidence", [-0.1, 1.5])
def test_judge_信心度必須在_0_到_1_之間(bad_confidence):
    with pytest.raises(ValidationError):
        JudgeResult(verdict="true_alarm", confidence=bad_confidence, reasoning="x")


def test_主動學習決定的形狀():
    decision = ALDecision(keep=True, reason="YOLO 分數低但確實跌倒", priority="high")

    assert (decision.keep, decision.priority) == (True, "high")

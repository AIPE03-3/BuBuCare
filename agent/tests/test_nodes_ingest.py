# agent/tests/test_nodes_ingest.py
# 驗收重點（WBS P1.1）：現有 vlm_worker 處理的訊息樣本 100% 通過；缺圖不 crash；
# 僅依賴 ImageStore 介面。

from agent.image_store import ImageNotFound, LocalImageStore
from agent.nodes.ingest import has_error, make_ingest_node

VALID_ALERT = {
    "event_type": "Fall_Detected",
    "camera_id": "101",
    "image_filename": "snapshot_101.jpg",
    "yolo_score": 0.72,
    "yolo_threshold": 0.5,
    "detected_at": "2026-07-19T15:30:00",
    "clip_path": "/vids/xxx.mp4",
}


class FakeStore:
    """只實作 resolve()——證明 ingest 真的只依賴介面，不認識具體後端。"""

    def __init__(self, path="/tmp/fake.jpg", error=None):
        self.path = path
        self.error = error
        self.asked = []

    def resolve(self, image_filename):
        self.asked.append(image_filename)
        if self.error:
            raise self.error
        return self.path


def test_合法訊息產出可信的_state(settings):
    ingest = make_ingest_node(FakeStore("/imgs/a.jpg"), settings.dlq_log_path)

    result = ingest({"raw": VALID_ALERT})

    assert result["alert"].device_id == 101
    assert result["image_path"] == "/imgs/a.jpg"
    assert result["error"] is None
    assert has_error(result) is False


def test_只依賴_ImageStore_介面(settings):
    # ingest 不知道也不在乎圖從哪來：換 local/s3 後端對它沒有差別
    store = FakeStore()
    make_ingest_node(store, settings.dlq_log_path)({"raw": VALID_ALERT})

    assert store.asked == ["snapshot_101.jpg"]


def test_搭配真的_LocalImageStore_也能跑(settings, image_dir):
    image_dir("snapshot_101.jpg")
    store = LocalImageStore(str(image_dir.dir), wait_seconds=0)

    result = make_ingest_node(store, settings.dlq_log_path)({"raw": VALID_ALERT})

    assert result["image_path"].endswith("snapshot_101.jpg")


def test_壞資料進_DLQ_不_crash(settings, read_jsonl):
    # camera_id 非數字：舊行為是硬塞 device_id=101，事件會掛到別台裝置上
    ingest = make_ingest_node(FakeStore(), settings.dlq_log_path)

    result = ingest({"raw": {**VALID_ALERT, "camera_id": "Unknown_Room"}})

    assert has_error(result) is True
    assert "validation_failed" in result["error"]
    records = read_jsonl(settings.dlq_log_path)
    assert len(records) == 1
    assert records[0]["reason"] == "validation_failed"
    assert records[0]["raw"]["camera_id"] == "Unknown_Room"   # 原始訊息留著，可重放


def test_缺圖進_DLQ_不_crash(settings, read_jsonl):
    store = FakeStore(error=ImageNotFound("找不到圖檔：/imgs/a.jpg"))
    ingest = make_ingest_node(store, settings.dlq_log_path)

    result = ingest({"raw": VALID_ALERT})

    assert has_error(result) is True
    assert read_jsonl(settings.dlq_log_path)[0]["reason"] == "image_not_found"


def test_缺可選欄位仍可受理(settings):
    # detected_at / clip_path 可能缺，由 publish 補
    minimal = {"event_type": "Fall_Detected", "camera_id": "101", "image_filename": "a.jpg"}

    result = make_ingest_node(FakeStore(), settings.dlq_log_path)({"raw": minimal})

    assert has_error(result) is False
    assert result["alert"].detected_at is None


def test_空訊息進_DLQ(settings, read_jsonl):
    result = make_ingest_node(FakeStore(), settings.dlq_log_path)({"raw": {}})

    assert has_error(result) is True
    assert read_jsonl(settings.dlq_log_path)[0]["reason"] == "validation_failed"


def test_重試計數器歸零(settings):
    # 每筆訊息都從零開始算重試，不會沿用上一筆的計數
    result = make_ingest_node(FakeStore(), settings.dlq_log_path)({"raw": VALID_ALERT})

    assert result["vlm_retries"] == 0
    assert result["judge_retries"] == 0

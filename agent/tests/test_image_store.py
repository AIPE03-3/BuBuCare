# agent/tests/test_image_store.py
# 驗收重點（WBS P0.6）：local 可解析開發機測試圖；s3 的下載/缺檔路徑有測試；
# 兩後端對 ingest 同型（都回傳本機絕對路徑，取不到都丟 ImageNotFound）。

import pytest

from agent.image_store import (
    ImageNotFound,
    LocalImageStore,
    S3ImageStore,
    build_image_store,
)


# ── LocalImageStore ─────────────────────────────────────
def test_local_找得到圖時回傳絕對路徑(image_dir):
    image_dir("snapshot_101.jpg")
    store = LocalImageStore(str(image_dir.dir), wait_seconds=0)

    path = store.resolve("snapshot_101.jpg")

    assert path.endswith("snapshot_101.jpg")
    assert path.startswith("/")  # 絕對路徑：VLM 要吃的是本機可讀路徑


def test_local_檔案還沒落地時會等一下再看一次(image_dir, monkeypatch):
    # 邊緣端可能「先發 Kafka、後寫檔」，等待期間檔案出現就該讀得到
    store = LocalImageStore(str(image_dir.dir), wait_seconds=0.01)
    target = "late.jpg"

    def fake_sleep(_seconds):
        image_dir(target)  # 模擬等待期間檔案才寫好

    monkeypatch.setattr("agent.image_store.time.sleep", fake_sleep)

    assert store.resolve(target).endswith(target)


def test_local_檔案不存在丟_ImageNotFound(image_dir):
    store = LocalImageStore(str(image_dir.dir), wait_seconds=0)

    with pytest.raises(ImageNotFound, match="找不到圖檔"):
        store.resolve("nope.jpg")


def test_local_沒帶檔名丟_ImageNotFound(image_dir):
    store = LocalImageStore(str(image_dir.dir), wait_seconds=0)

    with pytest.raises(ImageNotFound):
        store.resolve("")


def test_local_不再猜檔名(image_dir):
    # 舊 vlm_worker 找不到檔會改猜 snapshot_{cam_id}.jpg，猜錯時 VLM 讀到別張圖 → 判讀是錯的
    image_dir("snapshot_101.jpg")
    store = LocalImageStore(str(image_dir.dir), wait_seconds=0)

    with pytest.raises(ImageNotFound):
        store.resolve("snapshot_101_20260719_153000.jpg")


# ── S3ImageStore ────────────────────────────────────────
class FakeS3Client:
    """假的 boto3 client：記錄呼叫參數，可設定成下載失敗。"""

    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def download_file(self, bucket, key, local_path):
        self.calls.append((bucket, key, local_path))
        if self.fail:
            raise RuntimeError("NoSuchKey")
        with open(local_path, "wb") as f:
            f.write(b"downloaded-bytes")


def test_s3_下載後回傳本機路徑(tmp_path):
    client = FakeS3Client()
    store = S3ImageStore(bucket="b", prefix="snapshots", cache_dir=str(tmp_path), client=client)

    path = store.resolve("a.jpg")

    assert client.calls == [("b", "snapshots/a.jpg", str(tmp_path / "a.jpg"))]
    assert open(path, "rb").read() == b"downloaded-bytes"


def test_s3_沒設_prefix_時_key_就是檔名(tmp_path):
    client = FakeS3Client()
    store = S3ImageStore(bucket="b", prefix="", cache_dir=str(tmp_path), client=client)

    store.resolve("a.jpg")

    assert client.calls[0][1] == "a.jpg"


def test_s3_已在暫存目錄就不重複下載(tmp_path):
    client = FakeS3Client()
    store = S3ImageStore(bucket="b", cache_dir=str(tmp_path), client=client)
    (tmp_path / "a.jpg").write_bytes(b"cached")

    path = store.resolve("a.jpg")

    assert client.calls == []
    assert open(path, "rb").read() == b"cached"


def test_s3_下載失敗丟_ImageNotFound(tmp_path):
    # 缺檔、沒權限、斷線對下游沒差別，一律當成取不到圖 → ingest 記 DLQ 後跳過
    store = S3ImageStore(bucket="b", cache_dir=str(tmp_path), client=FakeS3Client(fail=True))

    with pytest.raises(ImageNotFound, match="S3 下載失敗"):
        store.resolve("a.jpg")


# ── factory：換部署位置只改環境變數 ────────────────────────
def test_factory_依設定選出對應後端(make_settings):
    assert isinstance(build_image_store(make_settings(image_source="local")), LocalImageStore)
    assert isinstance(
        build_image_store(make_settings(image_source="s3", s3_bucket="b")), S3ImageStore
    )


def test_兩種後端對下游同型(image_dir, tmp_path):
    # ingest 只認 resolve()：兩個後端都回傳「本機可讀的絕對路徑」，介面沒有差異
    image_dir("a.jpg")
    local = LocalImageStore(str(image_dir.dir), wait_seconds=0)
    s3 = S3ImageStore(bucket="b", cache_dir=str(tmp_path / "cache"), client=FakeS3Client())

    for store in (local, s3):
        path = store.resolve("a.jpg")
        assert path.startswith("/")
        assert open(path, "rb").read()  # 兩邊都是真的讀得到內容的本機檔案

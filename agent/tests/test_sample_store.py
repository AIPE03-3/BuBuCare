# agent/tests/test_sample_store.py
# 驗收重點（WBS P4.2）：每筆收錄樣本都有機器可讀的理由與優先級。

import json

from agent.sample_store import ActiveLearningStore

METADATA = {
    "event_type": "Fall_Detected",
    "camera_id": "101",
    "yolo_score": 0.41,
    "agent_verdict": "true_alarm",
    "keep_reason": "YOLO 僅 0.41 但複判確認跌倒，屬漏抓盲點",
    "priority": "high",
}


def test_圖檔被複製到_images_目錄(tmp_path, image_dir):
    src = image_dir("snapshot_101.jpg", b"jpeg-bytes")
    store = ActiveLearningStore(str(tmp_path / "dataset"))

    saved = store.save(src, METADATA)

    assert saved.endswith("images/snapshot_101.jpg")
    assert open(saved, "rb").read() == b"jpeg-bytes"


def test_sidecar_與圖檔同名放在_meta(tmp_path, image_dir):
    src = image_dir("snapshot_101.jpg")
    store = ActiveLearningStore(str(tmp_path / "dataset"))

    store.save(src, METADATA)

    sidecar = tmp_path / "dataset" / "meta" / "snapshot_101.json"
    assert sidecar.exists()
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["image"] == "snapshot_101.jpg"
    assert payload["keep_reason"] == METADATA["keep_reason"]
    assert payload["priority"] == "high"
    assert payload["collected_at"]      # 收錄時間自動補


def test_收錄理由是可讀的繁中不是跳脫字元(tmp_path, image_dir):
    # 這份檔案是給人挑樣本時看的，變成 \uXXXX 就沒用了
    src = image_dir("a.jpg")
    ActiveLearningStore(str(tmp_path / "dataset")).save(src, METADATA)

    raw = (tmp_path / "dataset" / "meta" / "a.json").read_text(encoding="utf-8")
    assert "漏抓盲點" in raw


def test_不產生假標註檔(tmp_path, image_dir):
    # 舊 vlm_worker 會寫一組寫死的假座標當 YOLO-Pose 標註，拿去回訓會毒害模型
    src = image_dir("a.jpg")
    dataset = tmp_path / "dataset"

    ActiveLearningStore(str(dataset)).save(src, METADATA)

    assert not (dataset / "labels").exists()


def test_首次寫入產生說明用的_README(tmp_path, image_dir):
    src = image_dir("a.jpg")
    dataset = tmp_path / "dataset"

    ActiveLearningStore(str(dataset)).save(src, METADATA)

    readme = (dataset / "README.md").read_text(encoding="utf-8")
    assert "為什麼沒有 labels/" in readme      # 日後有人翻到不會以為是漏寫


def test_README_不會被後續寫入覆蓋(tmp_path, image_dir):
    dataset = tmp_path / "dataset"
    store = ActiveLearningStore(str(dataset))
    store.save(image_dir("a.jpg"), METADATA)
    (dataset / "README.md").write_text("團隊自己補充的說明", encoding="utf-8")

    store.save(image_dir("b.jpg"), METADATA)

    assert (dataset / "README.md").read_text(encoding="utf-8") == "團隊自己補充的說明"


def test_多筆樣本各自獨立(tmp_path, image_dir):
    # 一圖一檔：並行寫不互相覆蓋，壞一筆不影響其他筆
    store = ActiveLearningStore(str(tmp_path / "dataset"))

    store.save(image_dir("a.jpg"), {**METADATA, "priority": "high"})
    store.save(image_dir("b.jpg"), {**METADATA, "priority": "low"})

    meta_dir = tmp_path / "dataset" / "meta"
    assert {p.name for p in meta_dir.glob("*.json")} == {"a.json", "b.json"}
    assert json.loads((meta_dir / "b.json").read_text())["priority"] == "low"


def test_圖檔不存在時不丟例外(tmp_path):
    # 收樣本失敗不該影響主流程：事件還是要照常送出去
    store = ActiveLearningStore(str(tmp_path / "dataset"))

    assert store.save("/does/not/exist.jpg", METADATA) is None

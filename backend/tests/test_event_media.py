# backend/tests/test_event_media.py
# GET /events/{id}/media：後端把 DB 裡的 s3:// 換成限時可播放網址（presigned URL）
# 測試不打真 AWS：把「向 S3 要簽章網址」的 client 換成假的，只驗後端自己的邏輯。

import pytest

from backend.core import s3


# ── 假的 S3 client：不連網，回一個看得懂的假網址，方便斷言 key 有帶對 ──
class FakeS3Client:
    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://signed.example/{Params['Bucket']}/{Params['Key']}?exp={ExpiresIn}"


@pytest.fixture(autouse=True)
def fake_s3(monkeypatch):
    # 把 s3.get_s3_client 換成回傳假 client，整個測試檔都不會碰到真 boto3/AWS
    monkeypatch.setattr(s3, "get_s3_client", lambda: FakeS3Client())


# ════════════════════════════════════════════════════════
# parse_s3_uri：把 s3://bucket/key 拆成 (bucket, key)
# ════════════════════════════════════════════════════════
def test_parse_s3_uri_normal():
    assert s3.parse_s3_uri("s3://aipe03-3/videos/x.mp4") == ("aipe03-3", "videos/x.mp4")


def test_parse_s3_uri_local_path_returns_none():
    # 舊事件存的是本機路徑，不是 s3://，要回 None（端點才知道給 null）
    assert s3.parse_s3_uri("C:/albert/clips/x.mp4") is None


def test_parse_s3_uri_empty_returns_none():
    assert s3.parse_s3_uri("") is None


def test_parse_s3_uri_none_returns_none():
    assert s3.parse_s3_uri(None) is None


def test_parse_s3_uri_missing_key_returns_none():
    # 只有 bucket、沒有 key，不算有效
    assert s3.parse_s3_uri("s3://aipe03-3") is None


# ════════════════════════════════════════════════════════
# GET /events/{id}/media
# ════════════════════════════════════════════════════════
def test_media_returns_presigned_urls(client, auth_headers, make_event):
    event = make_event(
        clip_path="s3://aipe03-3/videos/clip.mp4",
        snapshot_path="s3://aipe03-3/shots/snap.jpg",
    )
    res = client.get(f"/events/{event.event_id}/media", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert "aipe03-3/videos/clip.mp4" in body["clip_url"]
    assert "aipe03-3/shots/snap.jpg" in body["snapshot_url"]


def test_media_snapshot_null_when_no_snapshot(client, auth_headers, make_event):
    event = make_event(clip_path="s3://aipe03-3/videos/clip.mp4", snapshot_path=None)
    res = client.get(f"/events/{event.event_id}/media", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["clip_url"] is not None
    assert body["snapshot_url"] is None


def test_media_clip_null_when_local_path(client, auth_headers, make_event):
    # clip_path 是舊的本機路徑（非 s3://）→ clip_url 給 null，不報錯
    event = make_event(clip_path="C:/albert/clips/old.mp4", snapshot_path=None)
    res = client.get(f"/events/{event.event_id}/media", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["clip_url"] is None


def test_media_event_not_found(client, auth_headers):
    res = client.get("/events/does-not-exist/media", headers=auth_headers)
    assert res.status_code == 404


def test_media_requires_login(client, make_event):
    event = make_event()
    res = client.get(f"/events/{event.event_id}/media")
    assert res.status_code == 401

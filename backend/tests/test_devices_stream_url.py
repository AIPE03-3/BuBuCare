# test_devices_stream_url.py
# 測試頻道名 → WHEP 網址的組合規則（MEDIAMTX_BASE_URL 與頻道名任一為空就回 None）

from core import config
from devices.router import whep_url


def test_whep_url_combines_base_and_channel(monkeypatch):
    # 兩者都有 → 組成 {base}/{頻道名}/whep
    monkeypatch.setattr(config, "MEDIAMTX_BASE_URL", "http://192.168.1.108:8889")
    assert whep_url("cam_in") == "http://192.168.1.108:8889/cam_in/whep"


def test_whep_url_strips_trailing_slash(monkeypatch):
    # .env 結尾多打一個斜線也不該組出兩條斜線
    monkeypatch.setattr(config, "MEDIAMTX_BASE_URL", "http://192.168.1.108:8889/")
    assert whep_url("cam_out") == "http://192.168.1.108:8889/cam_out/whep"


def test_whep_url_returns_none_without_base(monkeypatch):
    # 這個環境沒有設 MediaMTX → 沒有串流可看
    monkeypatch.setattr(config, "MEDIAMTX_BASE_URL", "")
    assert whep_url("cam_in") is None


def test_whep_url_returns_none_without_channel(monkeypatch):
    # 這台裝置沒填頻道名 → 這條串流不存在
    monkeypatch.setattr(config, "MEDIAMTX_BASE_URL", "http://192.168.1.108:8889")
    assert whep_url(None) is None
    assert whep_url("") is None


def test_get_devices_returns_both_stream_urls(client, auth_headers, db_session, monkeypatch):
    # 裝置兩個頻道都有填 → 端點回兩條組好的網址
    from core.models import Device

    monkeypatch.setattr(config, "MEDIAMTX_BASE_URL", "http://192.168.1.108:8889")
    db_session.add(Device(device_id=90, device_name="測試鏡頭",
                          status="active", company_id=1,
                          stream_channel="cam_in", stream_channel_detect="cam_out"))
    db_session.commit()

    res = client.get("/devices", headers=auth_headers)
    target = next(d for d in res.json() if d["device_id"] == 90)
    assert target["stream_url"] == "http://192.168.1.108:8889/cam_in/whep"
    assert target["stream_url_detect"] == "http://192.168.1.108:8889/cam_out/whep"


def test_get_devices_detect_none_when_channel_missing(client, auth_headers, db_session, monkeypatch):
    # 手機那類鏡頭沒有偵測頻道 → stream_url_detect 回 null，前端據此顯示「此鏡頭無 AI 偵測」
    from core.models import Device

    monkeypatch.setattr(config, "MEDIAMTX_BASE_URL", "http://192.168.1.108:8889")
    db_session.add(Device(device_id=91, device_name="手機鏡頭",
                          status="active", company_id=1,
                          stream_channel="phone_a", stream_channel_detect=None))
    db_session.commit()

    res = client.get("/devices", headers=auth_headers)
    target = next(d for d in res.json() if d["device_id"] == 91)
    assert target["stream_url"] == "http://192.168.1.108:8889/phone_a/whep"
    assert target["stream_url_detect"] is None


def test_get_devices_returns_raw_channel_names(client, auth_headers, db_session, monkeypatch):
    # AI 端要的是「沒加工過的頻道名」，不是前端用的 WHEP 網址：
    # 瀏覽器走 WebRTC（8889/whep），ffmpeg/OpenCV 走 RTSP（8554），同一個頻道兩種協定。
    # 後端只給頻道名，各端自己接上本機的 base，搬機器就不用改資料庫。
    # albert 的推論程式「讀 cam_in → 畫框 → 推 cam_out」，兩個名字都需要。
    from core.models import Device

    monkeypatch.setattr(config, "MEDIAMTX_BASE_URL", "http://192.168.1.108:8889")
    db_session.add(Device(device_id=92, device_name="AI 鏡頭",
                          status="active", company_id=1,
                          stream_channel="cam_in", stream_channel_detect="cam_out"))
    db_session.commit()

    res = client.get("/devices", headers=auth_headers)
    target = next(d for d in res.json() if d["device_id"] == 92)
    assert target["stream_channel"] == "cam_in"
    assert target["stream_channel_detect"] == "cam_out"


def test_raw_channel_not_affected_by_base_url(client, auth_headers, db_session, monkeypatch):
    # 沒設 MEDIAMTX_BASE_URL 時 WHEP 網址組不出來（回 None），但原始頻道名照樣要給 AI 端
    from core.models import Device

    monkeypatch.setattr(config, "MEDIAMTX_BASE_URL", "")
    db_session.add(Device(device_id=93, device_name="無位址環境",
                          status="active", company_id=1,
                          stream_channel="cam_in", stream_channel_detect=None))
    db_session.commit()

    res = client.get("/devices", headers=auth_headers)
    target = next(d for d in res.json() if d["device_id"] == 93)
    assert target["stream_url"] is None
    assert target["stream_channel"] == "cam_in"
    assert target["stream_channel_detect"] is None

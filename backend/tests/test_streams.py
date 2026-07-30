# test_streams.py
# 串流身分驗證：前端拿登入 JWT 換一張 60 秒的「串流權杖」，
# MediaMTX 收到觀看請求後回頭打後端驗這張權杖。

from datetime import datetime, timedelta, timezone

from jose import jwt

from core.auth import decode_access_token
from core.config import ALGORITHM, SECRET_KEY


# ── 測試小工具 ───────────────────────────────────────────

def get_stream_token(client, auth_headers, channel="cam_in"):
    """走真正的發票端點拿一張權杖，不繞過去直接呼叫函式"""
    return client.post(f"/streams/{channel}/token", headers=auth_headers).json()["token"]


def mediamtx_body(**overrides):
    """模擬 MediaMTX 打來的請求。預設是「瀏覽器要看 cam_in」，測什麼就覆蓋什麼"""
    body = {
        "action": "read",
        "path": "cam_in",
        "protocol": "webrtc",
        "token": "",
        "user": "",
        "password": "",
        "ip": "192.168.54.30",
        "id": "1a2b3c",
        "query": "",
        "userAgent": "Mozilla/5.0",
    }
    body.update(overrides)
    return body


# ════════════════════════════════════════════════════════
# POST /streams/{channel}/token —— 發票（需登入）
# ════════════════════════════════════════════════════════

def test_issue_token_requires_login(client):
    # 沒登入就想換票 → 擋在門口。串流權杖只發給已登入的人
    res = client.post("/streams/cam_in/token")
    assert res.status_code == 401


def test_issue_token_returns_token_and_expiry(client, auth_headers):
    # 回應要同時給「票」和「幾秒後過期」——前端不必自己猜壽命
    res = client.post("/streams/cam_in/token", headers=auth_headers)
    assert res.status_code == 200

    body = res.json()
    assert body["token"]
    assert body["expires_in"] == 60


def test_issue_token_payload_fields(client, auth_headers):
    # 票裡要有三樣東西：
    #   sub   = 誰要看（員編），出事查得到
    #   scope = 「僅限串流」的章，用來跟登入 token 區分
    #           （兩者同一把 SECRET_KEY 簽，外觀無法分辨，只能靠這個欄位）
    #   path  = 綁死哪一個頻道
    res = client.post("/streams/cam_in/token", headers=auth_headers)
    payload = decode_access_token(res.json()["token"])

    assert payload["sub"] == "alice"
    assert payload["scope"] == "stream"
    assert payload["path"] == "cam_in"


def test_issue_token_binds_requested_channel(client, auth_headers):
    # 換一個頻道發票，票上的頻道要跟著變——不是寫死的
    res = client.post("/streams/cam_out/token", headers=auth_headers)
    payload = decode_access_token(res.json()["token"])

    assert payload["path"] == "cam_out"


# ════════════════════════════════════════════════════════
# POST /streams/auth —— 驗票（公開，MediaMTX 呼叫）
# ════════════════════════════════════════════════════════
# 這個端點有兩條分支，順序不可對調：
#   ① protocol=rtsp 且 action=read → 比對 .env 的帳密（AI 端的推論程式走這條）
#   ② 其餘一律 → 比對 60 秒短命權杖（瀏覽器走這條，還必須是 read + webrtc）
# 先判協定再驗票的原因：AI 端的 RTSP 請求若落進分支②，會在「必須是 webrtc」那關被擋。
#
# 回 204 代表放行、401 代表擋下——這是 MediaMTX 規定的格式，不是我們自己選的。


# ── 分支②：瀏覽器的短命權杖 ──────────────────────────────

def test_auth_allows_valid_token(client, auth_headers):
    # 正常路徑：瀏覽器拿著剛換的票要看 cam_in
    token = get_stream_token(client, auth_headers, "cam_in")
    res = client.post("/streams/auth", json=mediamtx_body(token=token))

    assert res.status_code == 204


def test_auth_rejects_garbage_token(client):
    # 亂打一串字 → 連解都解不開
    res = client.post("/streams/auth", json=mediamtx_body(token="not-a-jwt"))  # guardrail: allow

    assert res.status_code == 401


def test_auth_rejects_login_token(client, staff_token):
    # 登入 token 是真的、也沒過期，但它沒有 scope=stream 這個記號。
    # 擋掉它的意義：登入 token 一整天有效，若能拿來看畫面，60 秒的限制就形同虛設
    res = client.post("/streams/auth", json=mediamtx_body(token=staff_token))

    assert res.status_code == 401


def test_auth_rejects_wrong_channel(client, auth_headers):
    # 拿 cam_in 的票去看 cam_out → 擋。一張票只認一個頻道
    token = get_stream_token(client, auth_headers, "cam_in")
    res = client.post("/streams/auth", json=mediamtx_body(token=token, path="cam_out"))

    assert res.status_code == 401


def test_auth_rejects_publish_action(client, auth_headers):
    # 觀看票不能拿來推流。
    # 正常情況 MediaMTX 的 authHTTPExclude 會讓 publish 根本不打過來，這裡是第二道保險
    token = get_stream_token(client, auth_headers, "cam_in")
    res = client.post("/streams/auth", json=mediamtx_body(token=token, action="publish"))

    assert res.status_code == 401




def test_auth_rejects_expired_token(client):
    # 手工簽一張「昨天就過期」的票。
    # 不用 monkeypatch 改秒數：auth.py 是 from core.config import ... ，
    # 值在 import 那一刻就綁死了，patch 不到
    expired = jwt.encode(
        {
            "sub": "alice",
            "scope": "stream",
            "path": "cam_in",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=10),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    res = client.post("/streams/auth", json=mediamtx_body(token=expired))

    assert res.status_code == 401


def test_auth_accepts_null_optional_fields(client, auth_headers):
    # MediaMTX 有些欄位會送 null 而不是空字串。
    # 若 request model 把型別寫死成 str，Pydantic 會直接回 422，
    # 而 MediaMTX 收到 422（不是 401 也不是 204）的行為未定義 → 整套驗證失效
    token = get_stream_token(client, auth_headers, "cam_in")
    res = client.post("/streams/auth", json={
        "action": "read",
        "path": "cam_in",
        "protocol": "webrtc",
        "token": token,
        "user": None,
        "password": None,
        "ip": None,
        "id": None,
        "query": None,
        "userAgent": None,
    })

    assert res.status_code == 204


def test_auth_requires_no_login(client, auth_headers):
    # 這個端點必須是公開的——呼叫它的是 MediaMTX，MediaMTX 沒有帳號、不會登入。
    # 安全性來自「沒有有效權杖就一定 401」，不是來自「誰能呼叫它」
    token = get_stream_token(client, auth_headers, "cam_in")
    res = client.post("/streams/auth", json=mediamtx_body(token=token))  # 不帶 Authorization

    assert res.status_code == 204


# ── 分支①：RTSP 讀取一律放行 ─────────────────────────────
# AI 端的推論程式「讀 cam_in → 畫框 → 推 cam_out」，讀的那一段走 RTSP，
# 不可能持有瀏覽器才拿得到的短命權杖，故直接放行、不另設憑證。
# 前提是攝影機／MediaMTX／AI 主機同屬受控內網（正式環境應切獨立網段）。

def test_rtsp_read_allowed_without_credentials(client):
    # 不帶權杖也不帶帳密 → 放行。AI 端就是這樣連的
    res = client.post("/streams/auth", json=mediamtx_body(
        protocol="rtsp", user=None, password=None, token=None,
    ))

    assert res.status_code == 204


def test_rtsp_publish_still_goes_through_token_branch(client):
    # 只有「讀取」放行。RTSP 推流會落進權杖分支，沒票就擋——
    # 正常情況 MediaMTX 的 authHTTPExclude 讓 publish 根本不會打過來，這是第二道保險
    res = client.post("/streams/auth", json=mediamtx_body(
        protocol="rtsp", action="publish", token=None,
    ))

    assert res.status_code == 401


# ════════════════════════════════════════════════════════
# 反向檢查：串流權杖不可用於一般 API
# ════════════════════════════════════════════════════════
# 兩種票由同一把 SECRET_KEY 簽，外觀分不出來，所以兩邊門口都要檢查：
#   /streams/auth   ：沒有 scope=stream → 擋（上面已測）
#   get_current_user：有  scope=stream → 擋（以下）
#
# 實際危害不大（串流權杖沒有 role，admin 端點仍被 require_admin 擋在 403），
# 但權杖會寫進 MediaMTX 與 nginx 的存取紀錄，log 外流時 60 秒內可被冒用。
# 一張票只該能做一件事。

def _stream_token_headers(client, auth_headers):
    return {"Authorization": f"Bearer {get_stream_token(client, auth_headers)}"}


def test_stream_token_rejected_by_normal_api(client, auth_headers):
    res = client.get("/me", headers=_stream_token_headers(client, auth_headers))
    assert res.status_code == 401


def test_stream_token_rejected_by_events_api(client, auth_headers):
    res = client.get("/events", headers=_stream_token_headers(client, auth_headers))
    assert res.status_code == 401


def test_stream_token_cannot_issue_another_token(client, auth_headers):
    # 拿串流權杖再去換一張新的 → 擋。否則 60 秒的壽命可以無限續，等同永不過期
    res = client.post("/streams/cam_in/token",
                      headers=_stream_token_headers(client, auth_headers))
    assert res.status_code == 401


def test_login_token_still_works(client, auth_headers):
    # 反向確認：正常的登入 token 沒被一起擋掉。
    # AI 端啟動時就是用登入 JWT 打 GET /devices 抓鏡頭清單，這條路不能斷
    res = client.get("/me", headers=auth_headers)
    assert res.status_code == 200

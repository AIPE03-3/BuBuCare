# test_streams.py
# 串流身分驗證：前端拿登入 JWT 換一張 60 秒的「串流權杖」，
# MediaMTX 收到觀看請求後回頭打後端驗這張權杖。

from core.auth import decode_access_token


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

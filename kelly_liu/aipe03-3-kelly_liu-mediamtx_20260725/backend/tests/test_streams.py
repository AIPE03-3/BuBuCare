from backend.core.auth import create_stream_token, decode_access_token


def test_stream_token_contains_restricted_claims():
    token = create_stream_token("my_camera_tapo", "alice")
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "alice"
    assert payload["scope"] == "stream"
    assert payload["path"] == "my_camera_tapo"


def test_issue_stream_token_requires_login(client):
    response = client.post("/streams/my_camera_tapo/token")
    assert response.status_code == 401


def test_logged_in_user_can_issue_stream_token(client, auth_headers):
    response = client.post("/streams/my_camera_tapo/token", headers=auth_headers)
    assert response.status_code == 200
    payload = decode_access_token(response.json()["token"])
    assert payload is not None
    assert payload["scope"] == "stream"
    assert payload["path"] == "my_camera_tapo"


def test_mediamtx_accepts_matching_webrtc_read(client):
    token = create_stream_token("my_camera_tapo", "alice")
    response = client.post(
        "/streams/auth",
        json={
            "token": token,
            "action": "read",
            "path": "my_camera_tapo",
            "protocol": "webrtc",
        },
    )
    assert response.status_code == 204


def test_mediamtx_rejects_wrong_path(client):
    token = create_stream_token("my_camera_tapo", "alice")
    response = client.post(
        "/streams/auth",
        json={
            "token": token,
            "action": "read",
            "path": "another_camera",
            "protocol": "webrtc",
        },
    )
    assert response.status_code == 401


def test_mediamtx_rejects_publish(client):
    token = create_stream_token("my_camera_tapo", "alice")
    response = client.post(
        "/streams/auth",
        json={
            "token": token,
            "action": "publish",
            "path": "my_camera_tapo",
            "protocol": "webrtc",
        },
    )
    assert response.status_code == 401

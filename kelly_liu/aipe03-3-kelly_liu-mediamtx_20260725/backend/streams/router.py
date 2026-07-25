from hmac import compare_digest
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from backend.core.auth import create_stream_token, decode_access_token
from backend.core.dependencies import get_current_user

router = APIRouter(prefix="/streams", tags=["streams"])


class StreamTokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_in: int


# class MediaMTXAuthRequest(BaseModel):
#     user: str = ""
#     password: str = ""
#     token: str = ""
#     ip: str = ""
#     action: str
#     path: str = ""
#     protocol: str = ""
#     id: str = ""
#     query: str = ""
#     userAgent: str = ""
class MediaMTXAuthRequest(BaseModel):
    user: str | None = ""
    password: str | None = ""
    token: str | None = ""
    ip: str | None = ""
    action: str
    path: str | None = ""
    protocol: str | None = ""
    id: str | None = None
    query: str | None = ""
    userAgent: str | None = ""


@router.post("/auth", status_code=status.HTTP_204_NO_CONTENT)
def authorize_mediamtx(request: MediaMTXAuthRequest) -> Response:
    """MediaMTX external HTTP auth callback：JWT 保護觀看、帳密保護推流。"""
    if request.action == "publish":
        from backend.core.config import MEDIAMTX_PUBLISH_PASS, MEDIAMTX_PUBLISH_USER

        allowed_publisher = (
            bool(MEDIAMTX_PUBLISH_USER)
            and bool(MEDIAMTX_PUBLISH_PASS)
            and compare_digest(request.user, MEDIAMTX_PUBLISH_USER)
            and compare_digest(request.password, MEDIAMTX_PUBLISH_PASS)
        )
        if allowed_publisher:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="publisher credentials invalid")

    payload: dict[str, Any] | None = decode_access_token(request.token)
    allowed = (
        payload is not None
        and payload.get("scope") == "stream"
        and payload.get("path") == request.path
        and request.action == "read"
        and request.protocol == "webrtc"
    )
    if not allowed:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="stream token invalid")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{camera_path}/token", response_model=StreamTokenResponse)
def issue_stream_token(
    camera_path: str,
    current_user: dict = Depends(get_current_user),
) -> StreamTokenResponse:
    """使用現有登入 JWT 換取只可觀看指定鏡頭的 60 秒串流 JWT。"""
    sub = current_user.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login token missing subject")

    from backend.core.config import STREAM_TOKEN_EXPIRE_SECONDS

    return StreamTokenResponse(
        token=create_stream_token(camera_path=camera_path, sub=str(sub)),
        expires_in=STREAM_TOKEN_EXPIRE_SECONDS,
    )

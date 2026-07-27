"""從後端 GET /devices 取得真實攝影機清單，組成 camera_worker 要的 {camera_id: stream_url}。

為什麼要有這支：以前 ai/inference_test.py 的 camera_channels 是寫死的三支 mp4，
後端裝置表就算填好了 stream_url，AI 端也看不到。接真實 RTSP 攝影機後，「有幾台、
拉哪個網址」是營運資料，該由後端裝置表當唯一真相，不該散在程式碼裡。

驗證方式：AI 端自己打 POST /login（form-encoded）拿 access_token，再帶
Authorization: Bearer 打 GET /devices —— 後端 GET /devices 的保護方式一行都沒改。
帳密只從環境變數讀，讀不到才退到 repo 根目錄的 .env（.env 已在 .gitignore，不進版控）。

單獨驗（不用起 Kafka/Triton）：
    cd ai && .venv/bin/python -c "import backend_devices as b; print(b.build_camera_channels())"
"""
import os
from pathlib import Path

import requests
from dotenv import dotenv_values

_REPO_ROOT = Path(__file__).resolve().parent.parent

# 刻意用 dotenv_values 而不是 load_dotenv：只讀成 dict，不把後端的 DB_PASSWORD/SECRET_KEY
# 灌進本行程的 os.environ（AI 端不需要那些，少一個誤用面）。真實環境變數優先於 .env。
_DOTENV = dotenv_values(_REPO_ROOT / ".env")


def _cfg(key: str, default: str = "") -> str:
    return os.environ.get(key) or _DOTENV.get(key) or default


# inference_test 的 CLIP_* / S3 憑證也要走同一套「真實環境變數優先於 .env」的取值規則，
# 對外公開一個 alias 避免各處自己再 dotenv_values 一次（_cfg 本身不動，既有呼叫端零改動）。
cfg = _cfg


# ⚠️ 變數名不要跟 TRITON_*_URL 混：Triton 的預設 URL 同樣寫 127.0.0.1:8000（實際掛 8010），
# 兩者混在一起看 log 會分不清是在打推論還是打後端。
BACKEND_API_URL = _cfg("BACKEND_API_URL", "http://127.0.0.1:8000").rstrip("/")
BACKEND_API_USER = _cfg("BACKEND_API_USER", "A001")   # init_db 種的管理員員編，不是機密
BACKEND_API_PASSWORD = _cfg("BACKEND_API_PASSWORD")   # 無預設：沒設就 fail fast，不猜
BACKEND_HTTP_TIMEOUT = float(_cfg("BACKEND_HTTP_TIMEOUT", "10"))


class BackendUnavailable(RuntimeError):
    """後端連不上／登入失敗／清單為空 —— 呼叫端負責印診斷並收工，不要靜默跑空。"""


def login(base_url: str = None, username: str = None,
          password: str = None, timeout: float = None) -> str:
    """打 POST /login 換 access_token。

    後端用的是 OAuth2PasswordRequestForm，所以是 form-encoded（data=），不是 JSON。
    """
    base_url = (base_url or BACKEND_API_URL).rstrip("/")
    username = username or BACKEND_API_USER
    password = BACKEND_API_PASSWORD if password is None else password
    timeout = timeout or BACKEND_HTTP_TIMEOUT

    if not password:
        raise BackendUnavailable(
            "未設定 BACKEND_API_PASSWORD（環境變數或 repo 根目錄 .env 都沒有）")

    try:
        res = requests.post(f"{base_url}/login",
                            data={"username": username, "password": password},
                            timeout=timeout)
    except requests.RequestException as e:
        raise BackendUnavailable(f"連不上後端 {base_url}：{e}") from e

    if res.status_code != 200:
        raise BackendUnavailable(
            f"登入失敗 HTTP {res.status_code}（帳號 {username}）：{res.text[:200]}")

    token = res.json().get("access_token")
    if not token:
        raise BackendUnavailable(f"登入回應沒有 access_token：{res.text[:200]}")
    return token


def fetch_devices(token: str, base_url: str = None, timeout: float = None) -> list:
    """打 GET /devices 取全部裝置（含 device_id / status / stream_url）。"""
    base_url = (base_url or BACKEND_API_URL).rstrip("/")
    timeout = timeout or BACKEND_HTTP_TIMEOUT
    try:
        res = requests.get(f"{base_url}/devices",
                           headers={"Authorization": f"Bearer {token}"},
                           timeout=timeout)
    except requests.RequestException as e:
        raise BackendUnavailable(f"取裝置清單失敗，連不上 {base_url}：{e}") from e

    if res.status_code != 200:
        raise BackendUnavailable(
            f"GET /devices 回 HTTP {res.status_code}：{res.text[:200]}")
    return res.json()


def build_camera_channels(base_url: str = None, username: str = None,
                          password: str = None, timeout: float = None) -> dict:
    """登入 → 取清單 → 過濾 → 組成 {camera_id: stream_url}。

    只取 status=active 且 stream_url 非空的裝置：inactive/fault 是人為停用或報修中，
    不該讓 worker 去無限重連；stream_url 空的是還沒接攝影機的裝置（例如純事件用的 1/2）。
    """
    token = login(base_url, username, password, timeout)
    devices = fetch_devices(token, base_url, timeout)

    channels = {}
    for d in devices:
        url = (d.get("stream_url") or "").strip()
        if d.get("status") != "active" or not url:
            continue
        channels[camera_id_of(d["device_id"])] = url

    if not channels:
        raise BackendUnavailable(
            f"後端有 {len(devices)} 台裝置，但沒有任何一台同時滿足 status=active 且 stream_url 非空")
    return channels


def camera_id_of(device_id: int) -> str:
    """device_id -> camera_id（房號命名）。

    ⚠️ 只能從 device_id 生，絕不能摻 device_name：inference_test.py 是把 camera_id 裡
    「所有數字」挖出來當 Kafka payload 的 device_id（Room_301_Bed -> 301），名字裡多一個
    數字（例如「交誼廳-01」）就會生出 30101 這種對不到裝置的鬼編號，事件會被後端退件。
    301/302/303 生出來與原本寫死的名稱完全相同，快照檔名與 Kafka device_id 都不變。
    """
    return f"Room_{int(device_id)}_Bed"

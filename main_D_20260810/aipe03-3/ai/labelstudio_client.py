#!/usr/bin/env python3
"""Label Studio 的連線與取檔管線，給兩支同步腳本共用。

    ai/inference_to_labelstudio_sdk.py   偵測框（rectanglelabels）← RT-DETR
    ai/pose_to_labelstudio_sdk.py        骨架點（keypointlabels）← YOLO-Pose

兩支要做的事只差「推什麼標註、拉回來寫成什麼格式」，登入、CSRF、列 task、把 S3 上的
圖抓下來這些完全一樣。抽出來的理由不是省行數，是**登入方式會變**——這台的 Label Studio
1.23 關掉了 legacy token（見 `login()`），下次升級再變一次時，改一個地方就好。

設定一律走 `mlops_paths.cfg()`（真實環境變數優先於 repo 根目錄 `.env`）。
"""
import base64
import os
import sys

import requests

from mlops_paths import RAW_DATASET_DIR, cfg, export_aws_rw_env

LS_URL = cfg("LS_URL", "http://localhost:8082").rstrip("/")
LS_USERNAME = cfg("LABEL_STUDIO_USERNAME")
LS_PASSWORD = cfg("LABEL_STUDIO_PASSWORD")
HTTP_TIMEOUT = float(cfg("LS_HTTP_TIMEOUT", "30"))

IMAGES_DIR = os.path.join(RAW_DATASET_DIR, "images")
LABELS_DIR = os.path.join(RAW_DATASET_DIR, "labels")


def fail(msg: str):
    sys.exit(f"\n❌ {msg}")


# ── session ──────────────────────────────────────────────────────────────────
def login() -> requests.Session:
    """模擬瀏覽器登入拿 session cookie。

    為什麼不用 API token：這台的 Label Studio 是 1.23，**legacy token 認證預設關閉**
    （組織設定 legacy_api_tokens_enabled=0，實測打 /api/projects 回 401
    "legacy token authentication has been disabled for this organization"）。
    session 登入是目前唯一不必去改組織設定就能用的路。
    """
    if not LS_USERNAME or not LS_PASSWORD:
        fail("未設定 LABEL_STUDIO_USERNAME / LABEL_STUDIO_PASSWORD"
             "（環境變數或 repo 根目錄 .env 都沒有）")

    s = requests.Session()
    login_url = f"{LS_URL}/user/login/"
    try:
        s.get(login_url, timeout=HTTP_TIMEOUT)
    except requests.RequestException as e:
        fail(f"連不上 Label Studio（{LS_URL}）：{e}\n"
             f"   起服務：docker compose -p ai -f ai/docker-compose-labelstudio.yml up -d")

    s.headers.update({"Referer": login_url})
    r = s.post(login_url, data={
        "email": LS_USERNAME, "password": LS_PASSWORD,
        "csrfmiddlewaretoken": s.cookies.get("csrftoken", ""),
    }, allow_redirects=True, timeout=HTTP_TIMEOUT)
    if "login" in r.url:
        fail("Label Studio 登入失敗，檢查 LABEL_STUDIO_USERNAME / LABEL_STUDIO_PASSWORD")
    print(f"✅ 已登入 Label Studio：{LS_URL}（{LS_USERNAME}）")
    return s


def csrf(s: requests.Session) -> None:
    s.headers.update({"X-CSRFToken": s.cookies.get("csrftoken", "")})


# ── 專案與 task ──────────────────────────────────────────────────────────────
def get_project(s: requests.Session, project_id: int) -> dict:
    csrf(s)
    r = s.get(f"{LS_URL}/api/projects/{project_id}/", timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        fail(f"讀不到專案 {project_id}（HTTP {r.status_code}）")
    return r.json()


def parse_label_config(label_config: str, control_tag: str = "RectangleLabels"
                       ) -> tuple[str, str, set[str]]:
    """從專案的標註介面設定抽出 from_name / to_name 與可用標籤集合。

    寫死 label/image 會在別人改過介面之後靜默對不上（prediction 注進去但畫面上不顯示），
    所以動態探查。`control_tag` 指定要找哪一種控制項——同一個專案可以同時掛
    `<RectangleLabels>` 和 `<KeyPointLabels>`（pose 標註就是兩個都要），
    它們的 `name=` 不同，抓錯就會注到另一個控制項上、畫面照樣不顯示。

    找不到指定的標籤時**退回整份設定的寬鬆比對**（第一個帶 `toName=` 的控制項），
    那是本函式抽出來以前的行為——既有的偵測專案就是靠它跑起來的，不能因為這次
    多加了一個參數就把它弄壞。
    """
    import re
    head = re.search(rf'<{control_tag}\b([^>]*)>', label_config, re.I)
    if head is not None:
        block = re.search(rf'<{control_tag}\b[^>]*>(.*?)</{control_tag}>',
                          label_config, re.S | re.I)
        scope, attrs = (block.group(1) if block else ""), head.group(1)
    else:
        scope, attrs = label_config, label_config

    from_name = (re.search(r'name="([^"]+)"\s+toName=', attrs)
                 or re.search(r'name="([^"]+)"', attrs) or [None, "label"])[1]
    to_name = (re.search(r'toName="([^"]+)"', attrs) or [None, "image"])[1]
    return from_name, to_name, set(re.findall(r'<Label\s+value="([^"]+)"', scope))


def list_tasks(s: requests.Session, project_id: int) -> list[dict]:
    csrf(s)
    r = s.get(f"{LS_URL}/api/tasks/", params={"project": project_id, "page_size": 1000},
              timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        fail(f"讀不到 task 清單（HTTP {r.status_code}）")
    data = r.json()
    return data["tasks"] if isinstance(data, dict) and "tasks" in data else \
        (data.get("results", []) if isinstance(data, dict) else data)


def get_task(s: requests.Session, task_id: int) -> dict:
    csrf(s)
    return s.get(f"{LS_URL}/api/tasks/{task_id}/", timeout=HTTP_TIMEOUT).json()


def sync_storage(s: requests.Session, project_id: int) -> None:
    """要求 Label Studio 重新同步 S3 來源（有新快照上傳到 S3 時才需要）。"""
    csrf(s)
    r = s.get(f"{LS_URL}/api/storages/s3", params={"project": project_id},
              timeout=HTTP_TIMEOUT)
    storages = r.json() if r.status_code == 200 else []
    storages = storages.get("results", storages) if isinstance(storages, dict) else storages
    if not storages:
        print("ℹ️ 這個專案沒有設定 S3 來源，略過同步")
        return
    for st in storages:
        rr = s.post(f"{LS_URL}/api/storages/s3/{st['id']}/sync", timeout=HTTP_TIMEOUT)
        print(f"🔄 S3 storage #{st['id']}（{st.get('title')}）sync → HTTP {rr.status_code}")


def replace_prediction(s: requests.Session, task_id: int, model_version: str,
                       result: list[dict], score: float) -> tuple[bool, str]:
    """清掉這個 task 的舊預測再注入新的。回傳 (成功, 訊息)。

    一定要先清：不然每跑一次就疊一層 prediction，審核畫面會一團亂。
    """
    csrf(s)
    detail = get_task(s, task_id)
    for old in detail.get("predictions", []):
        if old.get("id"):
            s.delete(f"{LS_URL}/api/predictions/{old['id']}/", timeout=HTTP_TIMEOUT)

    r = s.post(f"{LS_URL}/api/predictions/", json={
        "task": task_id, "model_version": model_version,
        "result": result, "score": score,
    }, timeout=HTTP_TIMEOUT)
    if r.status_code in (200, 201):
        return True, ""
    return False, f"HTTP {r.status_code}：{r.text[:160]}"


# ── 影像取得 ─────────────────────────────────────────────────────────────────
def resolve_image_url(task: dict) -> str:
    """Label Studio 的 data.image 可能是 `/tasks/N/resolve/?fileuri=<base64 的 s3:// 網址>`。"""
    url = (task.get("data") or {}).get("image", "")
    if "fileuri=" in url:
        b64 = url.split("fileuri=")[-1]
        b64 += "=" * ((4 - len(b64) % 4) % 4)
        try:
            return base64.b64decode(b64).decode("utf-8", errors="ignore")
        except Exception:
            return url
    return url


def local_image_path(image_url: str, task_id: int) -> str:
    name = image_url.rstrip("/").split("/")[-1] or f"task_{task_id}.jpg"
    return os.path.join(IMAGES_DIR, name)


def ensure_local_image(image_url: str, path: str):
    """本地沒有就從 S3 抓下來；回傳 BGR 影像（取不到回 None）。"""
    import cv2
    import numpy as np
    if os.path.exists(path):
        return cv2.imread(path)
    if not image_url.startswith("s3://"):
        return None
    import boto3
    export_aws_rw_env()
    bucket, key = image_url[len("s3://"):].split("/", 1)
    try:
        body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as e:
        print(f"  ⚠️ S3 取檔失敗 {image_url}：{e}")
        return None
    img = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
    if img is not None:
        os.makedirs(IMAGES_DIR, exist_ok=True)
        cv2.imwrite(path, img)
    return img

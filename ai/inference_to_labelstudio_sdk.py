#!/usr/bin/env python3
"""Label Studio 串接：把 AI 預標註推進去、把人工標註拉回來成 YOLO 標籤檔。

移植自 `origin/albert_chiang:Fall/tools/inference_to_labelstudio_sdk.py`（394 行）。
它是主動學習飛輪的人機交界：

    邊緣端快照 ──> Label Studio task ──> AI 預標註(prediction)
                                            │
                                    人工開箱審核 / 修正 / Submit
                                            │
                                            v
                          本地 YOLO 標籤檔 ──> prepare_dataset ──> 重訓

兩個方向都做，靠「這個 task 有沒有人工標註」自動分流：
  · **有標註** → 把最新那筆人工標註轉成 YOLO 格式寫回本地（人工結果永遠優先）
  · **沒標註** → 跑一次推論，把結果當 prediction 注入，等人審核

## 與上游的差異（都是「照抄會出事」的地方）

1. **類別對照表不再寫死在程式裡**。上游把 `ENV_LABEL_TO_YOLO` 硬編成
   `wheelchair/slipper/wire/obstacle/walker`，而這台 Label Studio 專案的標籤其實是
   `person/chair/sofa/bed/tv` —— 照抄會讓標籤名與 class id 全部對錯。改成從
   `ai/data.yaml` 讀（那份是唯一真相），對不上時**直接報錯不猜**。
2. **推論改打線上的 Triton `rt_detr`**，不再另外載一份本地權重。理由：要驗的就是
   「線上這顆模型現在畫得如何」，另載一份等於在驗一個沒有上線的東西；而且省掉
   幾百 MB 的重複權重與 GPU 記憶體。
3. **拿掉寫死的預設帳號**（上游是某人的 gmail）。帳密只從環境變數／根目錄 `.env` 讀，
   沒設就 fail fast，不猜。
4. 上游那段「第十九關」對 S3 storage 連打 sync/realize/reimport 三個端點並吞掉所有
   例外，改成只在 `--sync-storage` 時做、且回報結果。

用法（都要先起好 Label Studio，見 ai/docker-compose-labelstudio.yml）：
    python ai/inference_to_labelstudio_sdk.py              # 雙向同步
    python ai/inference_to_labelstudio_sdk.py --pull-only  # 只把人工標註拉回本地
    python ai/inference_to_labelstudio_sdk.py --sync-storage
"""
import argparse
import base64
import os
import sys

import numpy as np
import requests

from mlops_paths import AI_DIR, DATA_YAML, RAW_DATASET_DIR, cfg, export_aws_rw_env

LS_URL = cfg("LS_URL", "http://localhost:8082").rstrip("/")
LS_PROJECT_ID = int(cfg("LS_PROJECT_ID", "1"))
LS_USERNAME = cfg("LABEL_STUDIO_USERNAME")
LS_PASSWORD = cfg("LABEL_STUDIO_PASSWORD")
CONF_THRES = float(cfg("LS_CONF_THRES", "0.35"))
HTTP_TIMEOUT = float(cfg("LS_HTTP_TIMEOUT", "30"))

IMAGES_DIR = os.path.join(RAW_DATASET_DIR, "images")
LABELS_DIR = os.path.join(RAW_DATASET_DIR, "labels")

# 線上 rt_detr 目前是 COCO 80 類的 rtdetr-l，而專案標籤是 person/chair/sofa/bed/tv。
# 這張表把 COCO 名字轉成專案標籤名（couch→sofa 是唯一需要改名的）。
# 換成重訓後的模型時設 LS_PREDICT_SOURCE=native —— 那顆的 class id 已經就是專案標籤序。
COCO_TO_PROJECT = {"person": "person", "chair": "chair", "couch": "sofa",
                   "bed": "bed", "tv": "tv"}
PREDICT_SOURCE = cfg("LS_PREDICT_SOURCE", "coco")


def fail(msg: str):
    sys.exit(f"\n❌ {msg}")


def load_class_map() -> dict[str, int]:
    """從 ai/data.yaml 讀 names，回傳 {標籤名: class_id}。"""
    import yaml
    with open(DATA_YAML, encoding="utf-8") as f:
        names = yaml.safe_load(f)["names"]
    return {v: int(k) for k, v in names.items()}


# ── Label Studio session ─────────────────────────────────────────────────────
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


def _csrf(s: requests.Session) -> None:
    s.headers.update({"X-CSRFToken": s.cookies.get("csrftoken", "")})


def get_project(s: requests.Session) -> dict:
    _csrf(s)
    r = s.get(f"{LS_URL}/api/projects/{LS_PROJECT_ID}/", timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        fail(f"讀不到專案 {LS_PROJECT_ID}（HTTP {r.status_code}）")
    return r.json()


def parse_label_config(label_config: str) -> tuple[str, str, set[str]]:
    """從專案的標註介面設定抽出 from_name / to_name 與可用標籤集合。

    寫死 label/image 會在別人改過介面之後靜默對不上（prediction 注進去但畫面上不顯示），
    所以照上游的做法動態探查，但多回傳一份標籤集合供對帳。
    """
    import re
    from_name = (re.search(r'name="([^"]+)"\s+toName=', label_config) or [None, "label"])[1]
    to_name = (re.search(r'toName="([^"]+)"', label_config) or [None, "image"])[1]
    labels = set(re.findall(r'<Label\s+value="([^"]+)"', label_config))
    return from_name, to_name, labels


def list_tasks(s: requests.Session) -> list[dict]:
    _csrf(s)
    r = s.get(f"{LS_URL}/api/tasks/", params={"project": LS_PROJECT_ID, "page_size": 1000},
              timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        fail(f"讀不到 task 清單（HTTP {r.status_code}）")
    data = r.json()
    return data["tasks"] if isinstance(data, dict) and "tasks" in data else \
        (data.get("results", []) if isinstance(data, dict) else data)


def sync_storage(s: requests.Session) -> None:
    """要求 Label Studio 重新同步 S3 來源（有新快照上傳到 S3 時才需要）。"""
    _csrf(s)
    r = s.get(f"{LS_URL}/api/storages/s3", params={"project": LS_PROJECT_ID},
              timeout=HTTP_TIMEOUT)
    storages = r.json() if r.status_code == 200 else []
    storages = storages.get("results", storages) if isinstance(storages, dict) else storages
    if not storages:
        print("ℹ️ 這個專案沒有設定 S3 來源，略過同步")
        return
    for st in storages:
        rr = s.post(f"{LS_URL}/api/storages/s3/{st['id']}/sync", timeout=HTTP_TIMEOUT)
        print(f"🔄 S3 storage #{st['id']}（{st.get('title')}）sync → HTTP {rr.status_code}")


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


def ensure_local_image(image_url: str, path: str) -> "np.ndarray | None":
    """本地沒有就從 S3 抓下來；回傳 BGR 影像。"""
    import cv2
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


# ── 兩個方向 ─────────────────────────────────────────────────────────────────
def pull_annotation(detail: dict, stem: str, cls_map: dict[str, int], stats) -> bool:
    """人工標註 → 本地 YOLO 標籤檔。回傳有沒有寫出東西。"""
    ann = detail.get("annotations") or []
    if not ann:
        return False
    lines = []
    for item in ann[-1].get("result", []):      # 取最新那一筆
        if item.get("type") != "rectanglelabels":
            continue
        val = item.get("value", {})
        labels = val.get("rectanglelabels") or []
        if not labels:
            continue
        name = labels[0]
        if name not in cls_map:
            # 不猜。標籤名對不上 data.yaml 就是設定不一致，要人去對，不是靜默丟掉
            stats["標籤名不在 data.yaml"] += 1
            print(f"  ⚠️ 標籤 '{name}' 不在 ai/data.yaml 的 names 裡，這一個框跳過")
            continue
        # Label Studio 用百分比的左上角座標，YOLO 用正規化的中心點
        x, y = val.get("x", 0.0), val.get("y", 0.0)
        w, h = val.get("width", 0.0), val.get("height", 0.0)
        cx, cy = (x + w / 2) / 100, (y + h / 2) / 100
        nw, nh = w / 100, h / 100
        clip = lambda v: min(max(v, 0.0), 1.0)  # noqa: E731
        lines.append(f"{cls_map[name]} {clip(cx):.6f} {clip(cy):.6f} "
                     f"{clip(nw):.6f} {clip(nh):.6f}")

    os.makedirs(LABELS_DIR, exist_ok=True)
    with open(os.path.join(LABELS_DIR, f"{stem}.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))
    stats["拉回・人工標註"] += 1
    stats["拉回・框數"] += len(lines)
    return True


def push_prediction(s: requests.Session, task_id: int, img, cls_map, model,
                    from_name: str, to_name: str, stats) -> None:
    """跑推論 → 注入 prediction 等人審核。"""
    h, w = img.shape[:2]
    results = model(img, conf=CONF_THRES, verbose=False)
    ls_result = []
    for box in (results[0].boxes if results else []):
        cls_id = int(box.cls[0].item())
        if PREDICT_SOURCE == "native":
            # 重訓後的模型：class id 已經就是專案標籤序
            name = next((n for n, i in cls_map.items() if i == cls_id), None)
        else:
            name = COCO_TO_PROJECT.get(model.names.get(cls_id, ""))
        if name is None or name not in cls_map:
            continue
        x1, y1, x2, y2 = box.xyxy.cpu().numpy()[0]
        # ⚠️ 一定要 float()：numpy 的 float32 過不了 json.dumps
        #（TypeError: Object of type float32 is not JSON serializable），
        # 而 round() 拿到 np.float32 回傳的仍是 np.float32，不會幫你轉。
        pct = lambda v: float(round(float(v) * 100, 4))  # noqa: E731
        ls_result.append({
            "from_name": from_name, "to_name": to_name, "type": "rectanglelabels",
            "value": {"x": pct(x1 / w), "y": pct(y1 / h),
                      "width": pct((x2 - x1) / w), "height": pct((y2 - y1) / h),
                      "rectanglelabels": [name]},
            "score": float(box.conf[0].item()),
        })

    # 先清掉這個 task 的舊預測，不然每跑一次就疊一層，審核畫面會一團亂
    _csrf(s)
    detail = s.get(f"{LS_URL}/api/tasks/{task_id}/", timeout=HTTP_TIMEOUT).json()
    for old in detail.get("predictions", []):
        if old.get("id"):
            s.delete(f"{LS_URL}/api/predictions/{old['id']}/", timeout=HTTP_TIMEOUT)

    r = s.post(f"{LS_URL}/api/predictions/", json={
        "task": task_id, "model_version": f"rt_detr@triton({PREDICT_SOURCE})",
        "result": ls_result,
        "score": float(np.mean([i["score"] for i in ls_result])) if ls_result else 0.0,
    }, timeout=HTTP_TIMEOUT)
    if r.status_code in (200, 201):
        stats["推入・AI 預標註"] += 1
        stats["推入・框數"] += len(ls_result)
    else:
        stats["推入・失敗"] += 1
        print(f"  ❌ 預標註注入失敗 HTTP {r.status_code}：{r.text[:160]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Label Studio 雙向同步（AI 預標註 / 人工標註回收）")
    ap.add_argument("--pull-only", action="store_true", help="只把人工標註拉回本地，不做推論")
    ap.add_argument("--sync-storage", action="store_true", help="先要求 Label Studio 重新同步 S3 來源")
    ap.add_argument("--limit", type=int, help="只處理前 N 個 task（除錯用）")
    args = ap.parse_args()

    cls_map = load_class_map()
    print(f"類別對照（來自 {os.path.relpath(DATA_YAML, AI_DIR)}）：{cls_map}")

    s = login()
    project = get_project(s)
    from_name, to_name, ui_labels = parse_label_config(project.get("label_config", ""))
    print(f"專案：{project.get('title')}（task {project.get('task_number')}，"
          f"已標註 {project.get('num_tasks_with_annotations')}）")
    print(f"標註介面：from_name={from_name} to_name={to_name} 標籤={sorted(ui_labels)}")

    # 對帳：介面上的標籤與 data.yaml 對不上就直接停，不要標到一半才發現類別錯位
    missing = ui_labels - set(cls_map)
    if missing:
        fail(f"Label Studio 介面有 data.yaml 沒有的標籤：{sorted(missing)}\n"
             f"   兩邊的類別必須一致，否則重訓出來的 class id 語意會錯。\n"
             f"   改 ai/data.yaml 的 names，或改 Label Studio 的標註介面設定。")

    if args.sync_storage:
        sync_storage(s)

    tasks = list_tasks(s)
    if args.limit:
        tasks = tasks[:args.limit]
    print(f"共 {len(tasks)} 個 task 要處理\n")

    model = None
    from collections import Counter
    stats = Counter()

    for i, task in enumerate(tasks, 1):
        image_url = resolve_image_url(task)
        path = local_image_path(image_url, task["id"])
        stem = os.path.splitext(os.path.basename(path))[0]

        _csrf(s)
        detail = s.get(f"{LS_URL}/api/tasks/{task['id']}/", timeout=HTTP_TIMEOUT).json()

        if pull_annotation(detail, stem, cls_map, stats):
            print(f"[{i}/{len(tasks)}] ⬅️  {stem}：已有人工標註，拉回本地")
            continue
        if args.pull_only:
            stats["略過・尚未標註"] += 1
            continue

        img = ensure_local_image(image_url, path)
        if img is None:
            stats["略過・取不到影像"] += 1
            print(f"[{i}/{len(tasks)}] ⚠️  {stem}：取不到影像，跳過")
            continue

        if model is None:
            # 延遲載入：--pull-only 或全部都已標註時完全不必碰 Triton
            from mlops_paths import TRITON_HTTP_URL
            from triton_detr_client import TritonDetrModel
            url = f"{TRITON_HTTP_URL}/rt_detr"
            print(f"📦 推論走線上 Triton：{url}")
            model = TritonDetrModel(url)

        print(f"[{i}/{len(tasks)}] ➡️  {stem}：跑推論並注入 AI 預標註")
        push_prediction(s, task["id"], img, cls_map, model, from_name, to_name, stats)

    print("\n── 統計 ──")
    for k, v in sorted(stats.items()):
        print(f"  {k:<24} {v}")
    print(f"\n本地標籤目錄：{os.path.relpath(LABELS_DIR, AI_DIR)}")
    print("接著清洗與切分：python ai/prepare_dataset.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

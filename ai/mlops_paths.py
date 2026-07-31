"""MLOps 那幾支腳本共用的路徑與設定取值，全部以 `__file__` 為基準。

為什麼要有這支：移植進來的 MLOps 腳本（export / 清洗 / 訓練 / 部署 / 標註串接）每一支
都需要「ai/ 在哪」「.env 在哪」「Triton 在哪」，上游那批檔是各自寫死家目錄絕對路徑
（`/Users/albert/...`、`/home/rapubuntu/...`）——換一台機器就全炸，護欄也會擋。
集中在這裡一次講清楚，各腳本 import 就好。

設定取值一律走 `backend_devices.cfg()`（真實環境變數優先於 repo 根目錄 `.env`），
與 `ai/inference_test.py` 同一套規則。**不要再讀 `ai/.env`** —— 那支只有 ClearML 那條
歷史腳本在讀，`inference_test.py` 看不到，兩份設定分岔過一次就夠了（見 CLAUDE.md 第四節）。
"""
import os
import sys

AI_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(AI_DIR)

# 讓 ClearML agent 在別的 cwd 底下執行時，仍 import 得到同目錄的其他 MLOps 模組
if AI_DIR not in sys.path:
    sys.path.insert(0, AI_DIR)

from backend_devices import cfg  # noqa: E402  （上面那行 sys.path 要先跑）

# ── 資料集 ───────────────────────────────────────────────────────────────────
# 原始素材：邊緣端與 agent 落地的快照 + 標註（機器產物，.gitignore 排除）
RAW_DATASET_DIR = os.path.join(AI_DIR, "active_learning_dataset")
# 人工標註落地的兩個目錄。圖片共用一份，標註分開放：
#
#   active_learning_dataset/images/        ← 兩邊共用
#                          /labels/        ← 偵測框，inference_to_labelstudio_sdk.py 寫
#                          /pose_labels/   ← 骨架點，pose_to_labelstudio_sdk.py 寫
#
# **刻意不共用同一個 labels/**：同一張圖可能同時在兩個 Label Studio 專案裡被標，
# 兩支腳本都寫 `{stem}.txt` 的話後跑的會蓋掉先跑的——而且是靜默蓋掉。
# pose 標註（56 欄）雖然是偵測標註（5 欄）的超集，但反過來不成立，
# 被偵測那支蓋掉就等於關節點全丟。分開放就沒有這個特殊情況要處理。
RAW_LABELS_DIR = os.path.join(RAW_DATASET_DIR, "labels")
RAW_POSE_LABELS_DIR = os.path.join(RAW_DATASET_DIR, "pose_labels")
# 清洗後真正拿去訓練的資料集（prepare_dataset.py 產生，同樣不進 repo）
DATASET_DIR = os.path.join(AI_DIR, "detection_dataset")
# YOLO-Pose 重訓吃的（同樣是 prepare_dataset.py 的產物，不進 repo）。
# 為什麼要分成兩個目錄而不是共用一份：RT-DETR 看不懂關節點、YOLO-Pose 沒有關節點就
# 訓練不了，同一份原始標註要清成兩種格式。共用會讓其中一邊拿到不能用的標註檔。
POSE_DATASET_DIR = os.path.join(AI_DIR, "pose_dataset")
# 切分名單（**這個進版控**）：只放檔名，不放路徑，換機器照樣可重現同一組 train/val
SPLITS_DIR = os.path.join(AI_DIR, "dataset_splits")

DATA_YAML = os.path.join(AI_DIR, "data.yaml")
POSE_DATA_YAML = os.path.join(AI_DIR, "pose_data.yaml")
# 交給 ultralytics 的那份（含絕對路徑，執行時生成，不進 repo）
DATA_YAML_RUNTIME = os.path.join(AI_DIR, "data.runtime.yaml")

# ── Triton ───────────────────────────────────────────────────────────────────
# model repository 的位置。預設是版控裡那份，但**線上 serve 的不一定是它**：
# 沒有 NVIDIA GPU 的機器跑的是 `ai/triton_repo_cpu/`（make_cpu_repo.sh 把 KIND_GPU
# 換成 KIND_CPU 的產物）。部署腳本要寫進「Triton 真正掛載的那個目錄」才有意義，
# 寫進版控那份等於改了一個沒人在讀的地方。所以這裡可被環境變數覆蓋。
#
# ⚠️ 指到 triton_repo_cpu 時要知道：那是 make_cpu_repo.sh 的產物，重跑該腳本會
#    `rm -rf` 重建，新部署的版本目錄會消失（權重可從 ClearML 重新拉，不是資料遺失）。
TRITON_REPO_DIR = cfg("TRITON_REPO_DIR", os.path.join(AI_DIR, "triton_repo"))
# ⚠️ 8010 不是 8000：8000 被 backend 的 uvicorn 佔著（見 CLAUDE.md 第四節）。
# 上游那份 model_deployment_agent.py 寫死 8000，照抄會打到 FastAPI 拿 404。
TRITON_HTTP_URL = cfg("TRITON_HTTP_URL", "http://127.0.0.1:8010").rstrip("/")


def resolve_data_yaml(src: str = DATA_YAML) -> str:
    """把資料集 yaml 的相對路徑展開成絕對路徑，另存一份 `*.runtime.yaml` 回傳。

    為什麼要多這一手：ultralytics 解析 data.yaml 裡的相對 `path:` 是相對於
    `settings['datasets_dir']`（使用者層級的全域設定），**不是相對於 yaml 自己的位置**。
    ClearML agent 是在它自己的工作目錄底下跑訓練腳本，直接餵相對路徑的 data.yaml 會
    找不到資料；而改動全域 settings 是會影響整台機器其他專案的副作用。
    所以進版控的 data.yaml 維持相對（可攜、護欄不會擋），執行時轉一份絕對的出來用。

    `src` 預設是 RT-DETR 那份；YOLO-Pose 重訓傳 `POSE_DATA_YAML` 進來。產出檔名跟著
    來源走（`data.yaml` → `data.runtime.yaml`、`pose_data.yaml` → `pose_data.runtime.yaml`），
    兩條線各寫各的，不會互相蓋掉——共用一個固定檔名的話，兩支訓練同時在跑時後寫的那份
    會讓先啟動的那邊讀到別人的資料集，而且不會報錯。
    """
    import yaml

    with open(src, encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    base = spec.get("path", ".")
    base = base if os.path.isabs(base) else os.path.normpath(os.path.join(AI_DIR, base))
    spec["path"] = base
    for key in ("train", "val", "test"):
        if spec.get(key) and not os.path.isabs(spec[key]):
            spec[key] = os.path.normpath(os.path.join(base, spec[key]))

    stem = os.path.splitext(os.path.basename(src))[0]
    dst = os.path.join(AI_DIR, f"{stem}.runtime.yaml")
    with open(dst, "w", encoding="utf-8") as f:
        f.write("# 由 ai/mlops_paths.resolve_data_yaml() 自動生成，不要手改、不進版控。\n")
        f.write(f"# 來源：{os.path.relpath(src, AI_DIR)}\n")
        yaml.safe_dump(spec, f, allow_unicode=True, sort_keys=False)
    return dst


def export_env(*keys: str) -> list[str]:
    """把指定的設定值塞進 `os.environ`，回傳實際塞進去的 key。

    `cfg()` 刻意只讀成 dict、不污染 os.environ（少一個誤用面）。但 boto3 與 ClearML SDK
    只認真正的環境變數，所以需要用到它們的腳本得明確把「哪幾個」放出去——列舉而不是
    整份 `.env` 倒進去，避免後端的 DB_PASSWORD / SECRET_KEY 被無關的行程看到。
    """
    exported = []
    for k in keys:
        v = cfg(k)
        if v:
            os.environ[k] = v
            exported.append(k)
    return exported


def export_aws_rw_env() -> list[str]:
    """把 S3 讀寫金鑰對映成 boto3 / ClearML 認得的 AWS_* 名字。

    本專案刻意把讀寫（AI 端上傳）與唯讀（後端簽 presigned URL）分成兩組金鑰＝最小權限，
    見 CLAUDE.md 第三節。MLOps 要往 S3 寫模型權重，所以用 `S3_RW_*` 那組；
    沒設時退回唯讀那組，行為與改動前一致（只是寫入會失敗，錯誤訊息比靜默好）。
    """
    region = cfg("S3_RW_REGION") or cfg("S3_REGION")
    key = cfg("S3_RW_ACCESS_KEY_ID") or cfg("ACCESS_KEY_ID")
    secret = cfg("S3_RW_SECRET_ACCESS_KEY") or cfg("SECRET_ACCESS_KEY")
    out = []
    for name, value in (("AWS_DEFAULT_REGION", region),
                        ("AWS_ACCESS_KEY_ID", key),
                        ("AWS_SECRET_ACCESS_KEY", secret)):
        if value:
            os.environ[name] = value
            out.append(name)
    return out

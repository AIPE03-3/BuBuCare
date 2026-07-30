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
# 清洗後真正拿去訓練的資料集（prepare_dataset.py 產生，同樣不進 repo）
DATASET_DIR = os.path.join(AI_DIR, "detection_dataset")
# 切分名單（**這個進版控**）：只放檔名，不放路徑，換機器照樣可重現同一組 train/val
SPLITS_DIR = os.path.join(AI_DIR, "dataset_splits")

DATA_YAML = os.path.join(AI_DIR, "data.yaml")
# 交給 ultralytics 的那份（含絕對路徑，執行時生成，不進 repo）
DATA_YAML_RUNTIME = os.path.join(AI_DIR, "data.runtime.yaml")

# ── Triton ───────────────────────────────────────────────────────────────────
TRITON_REPO_DIR = os.path.join(AI_DIR, "triton_repo")
# ⚠️ 8010 不是 8000：8000 被 backend 的 uvicorn 佔著（見 CLAUDE.md 第四節）。
# 上游那份 model_deployment_agent.py 寫死 8000，照抄會打到 FastAPI 拿 404。
TRITON_HTTP_URL = cfg("TRITON_HTTP_URL", "http://127.0.0.1:8010").rstrip("/")


def resolve_data_yaml() -> str:
    """把 `ai/data.yaml` 的相對路徑展開成絕對路徑，寫成 `ai/data.runtime.yaml` 回傳。

    為什麼要多這一手：ultralytics 解析 data.yaml 裡的相對 `path:` 是相對於
    `settings['datasets_dir']`（使用者層級的全域設定），**不是相對於 yaml 自己的位置**。
    ClearML agent 是在它自己的工作目錄底下跑訓練腳本，直接餵相對路徑的 data.yaml 會
    找不到資料；而改動全域 settings 是會影響整台機器其他專案的副作用。
    所以進版控的 data.yaml 維持相對（可攜、護欄不會擋），執行時轉一份絕對的出來用。
    """
    import yaml

    with open(DATA_YAML, encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    base = spec.get("path", ".")
    base = base if os.path.isabs(base) else os.path.normpath(os.path.join(AI_DIR, base))
    spec["path"] = base
    for key in ("train", "val", "test"):
        if spec.get(key) and not os.path.isabs(spec[key]):
            spec[key] = os.path.normpath(os.path.join(base, spec[key]))

    with open(DATA_YAML_RUNTIME, "w", encoding="utf-8") as f:
        f.write("# 由 ai/mlops_paths.resolve_data_yaml() 自動生成，不要手改、不進版控。\n")
        f.write(f"# 來源：{os.path.relpath(DATA_YAML, AI_DIR)}\n")
        yaml.safe_dump(spec, f, allow_unicode=True, sort_keys=False)
    return DATA_YAML_RUNTIME


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

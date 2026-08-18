#!/usr/bin/env python3
"""把重訓產出的模型熱部署進 Triton：拉 best.pt → ONNX → TensorRT 引擎 → 熱載切版。

移植自 `origin/albert_chiang:Fall/tools/model_deployment_agent.py`（244 行）。
它是 MLOps 迴路的最後一段 —— 沒有它，重訓只是產出一個沒人用的檔案。

    ClearML 上標了 best 的模型 ──> 下載 .pt
                                     │  ultralytics export
                                     v
                              rt_detr/<v>/model.onnx
                                     │  trtexec（Blackwell 專屬引擎）
                                     v
                              rt_detr/<v>/model.plan
                                     │  改 version_policy + POST /load
                                     v
                              Triton 線上換大腦，服務不中斷

## 與上游的五處差異（每一處照抄都會出事）

1. **Triton 埠是 8010 不是 8000**。上游寫死 `http://localhost:8000`，那是這台 backend
   的 uvicorn —— 照抄會打到 FastAPI 拿 404，然後因為狀態碼不是 200 而回報「Triton 拒絕」。
2. **要編 TensorRT 引擎，不能只丟 ONNX**。這台的 `rt_detr` 是
   `platform: tensorrt_plan`，只放 model.onnx 會讓整支 Triton 起不來（explicit 模式
   一顆載入失敗全倒，事故記錄見 `ai/triton_repo/README.md`）。上游是 Mac、沒有 N 卡，
   所以他那份做到 ONNX 就停了。
3. **要改 `version_policy`**。`rt_detr/config.pbtxt` 明確鎖在某一版（就是為了防止
   Triton 自動載到沒驗過的版本），只把檔案丟進 `rt_detr/2/` 是不會生效的。
4. **連不上 Triton 要當失敗**。上游有一段「Mac 連不上 Triton 就 return True」的優雅
   降級 —— 在這台上那是謊報成功，會讓人以為部署好了而繼續往下走。
5. **加 mAP 門檻與回滾**。上游是拿到什麼就部署什麼。

## 回滾

    python ai/model_deployment_agent.py --rollback
把 `version_policy` 切回上一版並重新載入。舊版本的 `model.plan` 一律不刪，就是為了
這條路隨時走得通。

用法：
    python ai/model_deployment_agent.py                 # 拉雲端 best 部署成下一版
    python ai/model_deployment_agent.py --force         # mAP 沒過門檻也照部署
    python ai/model_deployment_agent.py --rollback
    python ai/model_deployment_agent.py --from-pt <path>  # 用本地 .pt 部署（跳過 ClearML）
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time

import requests

from mlops_paths import AI_DIR, TRITON_HTTP_URL, TRITON_REPO_DIR, cfg

MODEL_NAME = os.environ.get("DEPLOY_MODEL_NAME", "rt_detr")
MODEL_DIR = os.path.join(TRITON_REPO_DIR, MODEL_NAME)
CONFIG_PBTXT = os.path.join(MODEL_DIR, "config.pbtxt")
PROJECT_NAME = os.environ.get("CLEARML_PROJECT", "Fall_Detection")

# 沒到這個 mAP50 就不部署（--force 可略過）。與訓練端的 MAP50_GATE 是同一條線。
DEPLOY_MIN_MAP50 = float(cfg("DEPLOY_MIN_MAP50", "0.80"))

TRITON_IMAGE = os.environ.get("TRITON_IMAGE", "nvcr.io/nvidia/tritonserver:25.10-py3")
IMGSZ = 640

VERSION_RE = re.compile(r"version_policy\s*:\s*\{\s*specific\s*\{\s*versions\s*:\s*\[\s*(\d+)\s*\]")
PLATFORM_RE = re.compile(r'^\s*platform\s*:\s*"([^"]+)"', re.MULTILINE)


def die(msg: str):
    sys.exit(f"\n❌ {msg}")


# ── config.pbtxt 的版本鎖 ────────────────────────────────────────────────────
def current_served_version() -> int:
    with open(CONFIG_PBTXT, encoding="utf-8") as f:
        m = VERSION_RE.search(f.read())
    if not m:
        die(f"{CONFIG_PBTXT} 找不到 version_policy specific versions —— "
            f"這支只處理明確鎖版的設定，不要改成隱式載最大版（理由見 triton_repo/README.md）")
    return int(m.group(1))


def set_served_version(version: int) -> None:
    with open(CONFIG_PBTXT, encoding="utf-8") as f:
        text = f.read()
    new = VERSION_RE.sub(
        lambda m: m.group(0).replace(m.group(1), str(version), 1), text, count=1)
    with open(CONFIG_PBTXT, "w", encoding="utf-8") as f:
        f.write(new)
    print(f"📝 config.pbtxt 的 serving 版本改為 v{version}")


def served_platform() -> str:
    """這顆模型的 config.pbtxt 宣告的 platform（決定要不要編 TensorRT 引擎）。

    **判斷依據刻意是「這顆模型要什麼格式」，不是「這台機器有沒有 GPU」。**
    同一份程式碼在兩台都對：5060 Ti 部署 `rt_detr`（tensorrt_plan）照樣編引擎，
    沒有 N 卡的機器部署 `rt_detr_onnx` / `action_transformer`（onnxruntime_onnx）
    就只放 model.onnx —— 那兩顆本來就不吃 .plan，硬編也用不上。
    """
    with open(CONFIG_PBTXT, encoding="utf-8") as f:
        m = PLATFORM_RE.search(f.read())
    if not m:
        die(f"{CONFIG_PBTXT} 讀不到 platform —— 不猜，先確認這個模型要的是哪種格式")
    return m.group(1)


def existing_versions() -> list[int]:
    if not os.path.isdir(MODEL_DIR):
        return []
    return sorted(int(d) for d in os.listdir(MODEL_DIR)
                  if d.isdigit() and os.path.isdir(os.path.join(MODEL_DIR, d)))


# ── 取得權重 ─────────────────────────────────────────────────────────────────
def fetch_best_from_clearml() -> tuple[str, float | None]:
    """從 ClearML 拉最新標了 best 的權重，順便回傳那一輪的 mAP50。"""
    from clearml import Model, Task

    print("🔍 從 ClearML 找最新標了 best 的模型 ...")
    found = Model.query_models(project_name=PROJECT_NAME, tags=["best"])
    if not found:
        die(f"ClearML 專案 {PROJECT_NAME} 沒有任何標 best 的模型 —— 先跑重訓")

    def created(m):
        for attr in ("created", "last_update"):
            v = getattr(m, attr, None) or getattr(getattr(m, "data", None), attr, None)
            if v is not None:
                return v.timestamp() if hasattr(v, "timestamp") else float(v)
        return 0.0

    latest = sorted(found, key=created, reverse=True)[0]
    print(f"🎯 選中 {latest.id}（{latest.name}）")

    # mAP 由訓練端寫成 Task 參數（見 clearml_train_pipeline.py），這裡讀回來擋門檻
    map50 = None
    try:
        task_id = getattr(latest, "task", None)
        if task_id:
            params = Task.get_task(task_id=task_id).get_parameters() or {}
            raw = params.get("metrics/mAP50") or params.get("General/metrics/mAP50")
            map50 = float(raw) if raw is not None else None
    except Exception as e:
        print(f"⚠️ 讀不到這輪的 mAP（{e}），門檻檢查會被跳過")

    local = latest.get_local_copy()
    if not local or not os.path.exists(local):
        die("模型權重下載失敗")
    print(f"📥 權重已下載：{local}")
    return local, map50


# ── 轉檔 ─────────────────────────────────────────────────────────────────────
def export_onnx(pt_path: str, dst: str) -> None:
    """.pt → ONNX，參數必須與 ai/export_models.py 的 rt_detr 完全一致。

    固定 [1,3,640,640] + opset 16 —— 對上 config.pbtxt 的 dims，也是 TensorRT
    最省事的形式（固定 shape 不必給 optimization profile）。
    """
    from ultralytics import RTDETR
    print(f"🔄 匯出 ONNX（imgsz={IMGSZ}, opset=16, 固定 shape）...")
    out = RTDETR(pt_path).export(format="onnx", imgsz=IMGSZ, opset=16, dynamic=False)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        os.remove(dst)
    shutil.move(out, dst)
    print(f"✅ {os.path.relpath(dst, AI_DIR)}（{os.path.getsize(dst) / 1024 / 1024:.1f}MB）")


def build_plan(version: int) -> None:
    """ONNX → Blackwell TensorRT 引擎，走與 ai/export_models.py 相同的容器路徑。"""
    onnx_path = os.path.join(MODEL_DIR, str(version), "model.onnx")
    plan_path = os.path.join(MODEL_DIR, str(version), "model.plan")
    if os.path.exists(plan_path):
        # 舊檔沒先刪，trtexec 會在編譯跑完之後才在存檔那刻炸（見 export_models.py 的說明）
        os.remove(plan_path)
    print("🔧 編 TensorRT 引擎（FP16），要幾分鐘 ...")
    cmd = [
        "docker", "run", "--rm", "--gpus", "all",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "-v", f"{TRITON_REPO_DIR}:/models", TRITON_IMAGE,
        "/usr/src/tensorrt/bin/trtexec",
        f"--onnx=/models/{MODEL_NAME}/{version}/model.onnx",
        f"--saveEngine=/models/{MODEL_NAME}/{version}/model.plan",
        "--fp16",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.exists(plan_path):
        print("\n".join((proc.stderr or proc.stdout).strip().split("\n")[-15:]))
        die("trtexec 失敗，沒有產出引擎")
    print(f"✅ {os.path.relpath(plan_path, AI_DIR)}"
          f"（{os.path.getsize(plan_path) / 1024 / 1024:.1f}MB）")


# ── Triton 熱載 ──────────────────────────────────────────────────────────────
def reload_model(version: int) -> bool:
    """要求 Triton 重新載入模型，然後輪詢到該版本 READY。"""
    url = f"{TRITON_HTTP_URL}/v2/repository/models/{MODEL_NAME}/load"
    print(f"🔄 POST {url}")
    try:
        r = requests.post(url, timeout=180)
    except requests.exceptions.ConnectionError as e:
        # ⚠️ 上游在這裡 return True（他 Mac 沒 N 卡連不上 Triton）。在這台上連不上
        #    就是失敗，回報成功會讓人以為換好大腦了。
        die(f"連不上 Triton（{TRITON_HTTP_URL}）：{e}\n"
            f"   起服務： HTTP_PORT=8010 GRPC_PORT=8011 ./ai/run_triton.sh")
    if r.status_code == 400 and "polling is enabled" in r.text:
        print("ℹ️ Triton 是 poll 模式，會自己撿新版本")
    elif r.status_code != 200:
        print(f"❌ Triton 拒絕載入：HTTP {r.status_code} {r.text[:300]}")
        return False

    ready = f"{TRITON_HTTP_URL}/v2/models/{MODEL_NAME}/versions/{version}/ready"
    for i in range(30):
        try:
            if requests.get(ready, timeout=10).status_code == 200:
                print(f"🎉 {MODEL_NAME} v{version} READY —— 線上已換成新模型，服務未中斷")
                return True
        except requests.RequestException:
            pass
        print(f"⏳ 等待載入 ({i + 1}/30)")
        time.sleep(2)
    print("❌ 逾時，Triton 沒把該版本帶到 READY")
    return False


def triton_model_versions() -> list[str]:
    try:
        r = requests.post(f"{TRITON_HTTP_URL}/v2/repository/index", timeout=10)
        return [e.get("version") for e in r.json() if e.get("name") == MODEL_NAME]
    except Exception:
        return []


# ── 主流程 ───────────────────────────────────────────────────────────────────
def do_rollback() -> int:
    cur = current_served_version()
    older = [v for v in existing_versions() if v < cur]
    if not older:
        die(f"沒有比 v{cur} 更舊、可回滾的版本目錄")
    target = older[-1]
    # 要檢查的權重檔名同樣看 platform：tensorrt_plan 要 .plan、onnxruntime_onnx 要 .onnx。
    # 一律檢查 .plan 的話，ONNX 那條路會被誤判成「不能回滾」——而那正是回滾最需要能走的時候。
    weight_name = "model.plan" if served_platform() == "tensorrt_plan" else "model.onnx"
    weight = os.path.join(MODEL_DIR, str(target), weight_name)
    if not os.path.exists(weight):
        die(f"v{target} 沒有 {weight_name}，不能回滾到一個載不起來的版本")
    print(f"⏪ 回滾 {MODEL_NAME}：v{cur} → v{target}")
    set_served_version(target)
    return 0 if reload_model(target) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="把重訓產出的模型熱部署進 Triton")
    ap.add_argument("--rollback", action="store_true", help="切回上一個版本")
    ap.add_argument("--force", action="store_true", help="mAP 沒到門檻也照部署")
    ap.add_argument("--from-pt", help="直接用本地 .pt 部署，不走 ClearML")
    ap.add_argument("--version", type=int, help="部署成哪一版（預設現有最大版 +1）")
    args = ap.parse_args()

    if not os.path.exists(CONFIG_PBTXT):
        die(f"找不到 {CONFIG_PBTXT}")
    if args.rollback:
        return do_rollback()

    if args.from_pt:
        pt_path, map50 = args.from_pt, None
        if not os.path.exists(pt_path):
            die(f"找不到 {pt_path}")
    else:
        pt_path, map50 = fetch_best_from_clearml()

    # ── 門檻 ─────────────────────────────────────────────────────────────────
    if map50 is None:
        print(f"⚠️ 這輪沒有 mAP 記錄，跳過門檻檢查（門檻 {DEPLOY_MIN_MAP50}）")
    elif map50 < DEPLOY_MIN_MAP50:
        msg = (f"mAP50={map50:.4f} 未達部署門檻 {DEPLOY_MIN_MAP50}")
        if not args.force:
            die(f"{msg}\n"
                f"   模型沒有變好就換上去，等於拿線上服務做實驗。\n"
                f"   確定要部署（例如只是要驗證熱部署流程本身）請加 --force。")
        print(f"⚠️ {msg} —— 已用 --force 強制放行，這是刻意的降級")
    else:
        print(f"✅ mAP50={map50:.4f} ≥ 門檻 {DEPLOY_MIN_MAP50}")

    cur = current_served_version()
    version = args.version or (max(existing_versions() + [cur]) + 1)
    print(f"📦 目前 serving v{cur}，本次部署成 v{version}")

    onnx_path = os.path.join(MODEL_DIR, str(version), "model.onnx")
    export_onnx(pt_path, onnx_path)

    # 只有 tensorrt_plan 才需要編引擎。onnxruntime_onnx 上面那步就已經備妥了，
    # 硬去跑 trtexec 只會在沒有 N 卡的機器上失敗（而且產出的 .plan 也沒人載）。
    platform = served_platform()
    if platform == "tensorrt_plan":
        build_plan(version)
    else:
        print(f"ℹ️ platform={platform} —— 不需要 TensorRT 引擎，跳過 trtexec")

    set_served_version(version)
    if not reload_model(version):
        # 載不起來就把版本鎖切回去，不要留一個指向壞版本的設定檔
        print(f"↩️ 載入失敗，把 config.pbtxt 切回 v{cur}")
        set_served_version(cur)
        reload_model(cur)
        return 1

    print(f"\n舊版 v{cur} 的權重保留在 {os.path.relpath(os.path.join(MODEL_DIR, str(cur)), AI_DIR)}，"
          f"要切回去： python ai/model_deployment_agent.py --rollback")
    return 0


if __name__ == "__main__":
    sys.exit(main())

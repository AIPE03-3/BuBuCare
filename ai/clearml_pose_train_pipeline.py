#!/usr/bin/env python3
"""YOLO-Pose 滾動式重訓：繼承上一輪的 best、訓練、評估 pose mAP、把權重推上 S3 標記 best。

移植自 `origin/albert_chiang:Fall/tools/clearml_pose_train_pipeline.py`。
它是 `ai/clearml_train_pipeline.py`（RT-DETR）的姿態版本，兩條線各自獨立跑：

    RT-DETR（環境物件）      inference_to_labelstudio_sdk → prepare_dataset            → 這條的兄弟檔
    YOLO-Pose（人體骨架）    pose_to_labelstudio_sdk      → prepare_dataset --task pose → 本檔

## 為什麼跟 clearml_train_pipeline.py 有重複的程式碼

這兩支都是以 **standalone script** 上傳給 ClearML（`submit_task.py` 設
`detect_repository=False` + `set_packages([])`），agent 只會把**單一 .py 複製到暫存目錄**
執行，import 同目錄的兄弟模組不保證成功。所以 `_model_created`、`_resolve_data_yaml`
這類東西刻意各留一份、並且都有 `try: from mlops_paths ... except ImportError` 的退路。
這是既有檔案就定下的做法（見那支的檔頭），不是漏抽。

## 兩處與 RT-DETR 那條不同的地方

1. **門檻看的是 pose mAP50，不是 box mAP50。** YOLO-Pose 會同時報兩個數字：框畫得準
   （box）與關節點放得準（pose）。這條線要的是後者——框準但關節點全錯的模型對跌倒
   判定毫無用處，而 box mAP50 幾乎一定比 pose 高，拿它對門檻等於門檻形同虛設。
2. **模型標籤是 `["yolo", "pose", "best"]` 三個一組**，查詢繼承時也用這組。與 RT-DETR
   共用同一個 ClearML 專案，只靠 `best` 一個標籤會把兩種模型混在一起——
   下一輪繼承時把 RT-DETR 的權重餵給 YOLO-Pose，`load_state_dict` 會直接爆，
   或更糟：ultralytics 靜默重建一個沒繼承到任何東西的新模型。

## 上游那顆寫死的 Discord webhook

上游第 215 行把一組**可用的** Discord webhook token 寫成 `os.getenv` 的預設值，
等於機密進版控。這裡改成沒設環境變數就不通知（`notify()` 直接 return），
不留任何預設值。要開通知就設 `DISCORD_WEBHOOK_URL`。

直接跑（不經 ClearML agent，除錯用）：
    python ai/clearml_pose_train_pipeline.py
    TRAIN_EPOCHS=50 TRAIN_DEVICE=mps python ai/clearml_pose_train_pipeline.py
"""
import os
import sys

# ⚠️ 一定要在 import torch 之前設。Mac 的 MPS 後端缺少 ultralytics 用到的幾個算子，
# 沒有這個 fallback 會在訓練中途噴 NotImplementedError 直接死掉（不是慢，是停）。
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

# ── 定位 repo 的 ai/ ─────────────────────────────────────────────────────────
# agent 執行時 __file__ 在暫存目錄，所以優先看 submit_task 傳進來的參數/環境變數。
_AI_DIR = os.environ.get("AIPE03_AI_DIR") or os.path.dirname(os.path.abspath(__file__))

from clearml import Model, OutputModel, Task  # noqa: E402

PROJECT_NAME = os.environ.get("CLEARML_PROJECT", "Fall_Detection")
TASK_NAME = os.environ.get("CLEARML_POSE_TASK_NAME", "YOLOPose_Cloud_Incremental_Training")

S3_BUCKET = os.environ.get("AWS_BUCKET_NAME", "aipe03-3")
S3_OUTPUT_URI = f"s3://{S3_BUCKET}/clearml-artifacts/models/fall_pose/"

# 這組標籤是「這顆是 YOLO-Pose 的最佳權重」的唯一識別，繼承與熱部署都認它。
MODEL_TAGS_BEST = ["yolo", "pose", "best"]
MODEL_TAGS_REJECT = ["yolo", "pose", "below-gate"]

# pose mAP50 的驗收門檻。與 RT-DETR 那條分開設：關節點比框難，同一個數字對兩邊
# 不是同一個難度。預設沿用 0.80，實跑後可用 POSE_MAP50_GATE 調。
MAP50_GATE = float(os.environ.get("POSE_MAP50_GATE", "0.80"))


def _bootstrap_paths() -> str:
    """把 repo 的 ai/ 放進 sys.path，讓 mlops_paths 之類的同伴模組 import 得到。"""
    if _AI_DIR not in sys.path:
        sys.path.insert(0, _AI_DIR)
    return _AI_DIR


def _resolve_data_yaml() -> str:
    """取得含絕對路徑的 pose_data.yaml（理由見 mlops_paths.resolve_data_yaml 的說明）。

    agent 只複製單一腳本、import 不到同伴模組時退回在這裡自己展開一次。
    """
    try:
        from mlops_paths import POSE_DATA_YAML, resolve_data_yaml
        return resolve_data_yaml(POSE_DATA_YAML)
    except ImportError:
        import yaml
        src = os.path.join(_AI_DIR, "pose_data.yaml")
        with open(src, encoding="utf-8") as f:
            spec = yaml.safe_load(f)
        base = spec.get("path", ".")
        base = base if os.path.isabs(base) else os.path.normpath(os.path.join(_AI_DIR, base))
        spec["path"] = base
        for k in ("train", "val", "test"):
            if spec.get(k) and not os.path.isabs(spec[k]):
                spec[k] = os.path.normpath(os.path.join(base, spec[k]))
        dst = os.path.join(_AI_DIR, "pose_data.runtime.yaml")
        with open(dst, "w", encoding="utf-8") as f:
            yaml.safe_dump(spec, f, allow_unicode=True, sort_keys=False)
        return dst


def _model_created(m) -> float:
    """取模型建立時間當排序鍵，欄位名在不同 clearml 版本會變。

    ⚠️ 上游直接用 `m.created`，在這台的 clearml 2.1.10 上會噴
    `AttributeError: 'Model' object has no attribute 'created'`，
    整段「繼承上一輪最強大腦」會被 except 吞掉、每輪都從頭冷啟動——
    看起來一切正常，但滾動式重訓其實從來沒有滾動過。
    """
    for attr in ("created", "last_update", "published"):
        v = getattr(m, attr, None)
        if v is not None:
            return v.timestamp() if hasattr(v, "timestamp") else float(v)
    data = getattr(m, "data", None)
    for attr in ("created", "last_update"):
        v = getattr(data, attr, None) if data is not None else None
        if v is not None:
            return v.timestamp() if hasattr(v, "timestamp") else float(v)
    return 0.0


def _tag_map50(model) -> float:
    """從模型標籤裡讀回上一輪的 pose mAP50（標籤格式 `map50_0.9123`）。"""
    for tag in getattr(model, "tags", None) or []:
        if tag.startswith("map50_"):
            try:
                return float(tag[len("map50_"):])
            except ValueError:
                pass
    return 0.0


def notify(title: str, message: str, color: int) -> None:
    """Discord 通知。**沒設 DISCORD_WEBHOOK_URL 就什麼都不做。**

    ⚠️ 上游把一組可用的 webhook token 寫成 `os.getenv(..., "https://discord.com/...")`
    的預設值 —— 那是機密進版控，任何拿到這份 repo 的人都能往那個頻道發訊息。
    這裡不留預設值：要通知就自己設環境變數。
    """
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        return
    try:
        import requests
        requests.post(url, json={"embeds": [{
            "title": title, "description": message, "color": color,
        }]}, timeout=5)
    except Exception as e:
        print(f"⚠️ 發送 Discord 通知失敗（不影響訓練結果）：{e}")


def pick_base_weights() -> tuple[str, float]:
    """滾動式重訓的核心：找雲端上一輪標了 best 的 YOLO-Pose 權重來繼承。

    回傳 (權重路徑, 上一輪的 pose mAP50)。沒有可繼承的就冷啟動、成績算 0。
    """
    fallback = os.path.join(_AI_DIR, "yolo11s-pose.pt")
    fallback = fallback if os.path.exists(fallback) else "yolo11s-pose.pt"
    try:
        print("🔍 檢查雲端有沒有上一輪產出的 YOLO-Pose best 模型 ...")
        # ⚠️ 三個標籤都要帶。只查 best 會撈到 RT-DETR 那條線的模型（同一個專案）。
        found = Model.query_models(project_name=PROJECT_NAME, tags=MODEL_TAGS_BEST)
        if not found:
            print(f"ℹ️ 雲端還沒有任何 YOLO-Pose best 模型，本輪從 {fallback} 冷啟動")
            return fallback, 0.0
        latest = sorted(found, key=_model_created, reverse=True)[0]
        old_map50 = _tag_map50(latest)
        print(f"📥 找到上一輪的最新模型（id={latest.id}，pose mAP50={old_map50:.4f}），"
              f"拉權重下來繼承")
        local = latest.get_local_copy()
        if local and os.path.exists(local):
            print("🔄 繼承成功，這輪在它的基礎上繼續訓練")
            return local, old_map50
        print("⚠️ 權重下載不到，降級冷啟動")
    except Exception as e:
        print(f"⚠️ 查詢雲端 best 失敗（{e}），降級用 {fallback} 冷啟動")
    return fallback, 0.0


def resolve_device(requested: str) -> str:
    """`auto` 時依序挑 cuda → mps → cpu；其餘照傳入的值。

    為什麼要 auto：RT-DETR 那條固定跑 5060 Ti（`device="0"`），但骨架重訓在 Mac
    本機也要跑得起來（見 docs/MAC_SETUP_WBS.md）。寫死 "0" 在沒有 CUDA 的機器上
    ultralytics 會噴 `AssertionError: Invalid CUDA device`。
    """
    if requested != "auto":
        return requested
    import torch
    if torch.cuda.is_available():
        return "0"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def main() -> int:
    _bootstrap_paths()

    task = Task.init(project_name=PROJECT_NAME, task_name=TASK_NAME)

    # submit_task 把 ai/ 位置與超參數都放在 Task 參數裡，agent 執行時從這裡讀回來。
    # ⚠️ 不能改讀環境變數：agent 是另一個行程，不會繼承排隊端的 os.environ
    #    （實測踩過：排隊端設 TRAIN_EPOCHS=60，agent 這端印的是 epochs=1）。
    params = task.get_parameters() or {}

    def _param(name: str, env: str, default: str) -> str:
        return (params.get(f"General/{name}") or params.get(name)
                or os.environ.get(env) or default)

    ai_dir = params.get("General/ai_dir") or params.get("ai_dir")
    if ai_dir and os.path.isdir(ai_dir):
        globals()["_AI_DIR"] = ai_dir
        _bootstrap_paths()
        print(f"📁 由 Task 參數取得 ai/ 位置：{ai_dir}")

    task.output_uri = S3_OUTPUT_URI

    data_yaml = _resolve_data_yaml()
    print(f"📚 資料集定義：{data_yaml}")

    from ultralytics import YOLO
    base_weights, old_map50 = pick_base_weights()
    model = YOLO(base_weights)

    epochs = int(_param("epochs", "TRAIN_EPOCHS", "60"))
    device = resolve_device(_param("device", "TRAIN_DEVICE", "auto"))
    batch = int(_param("batch", "TRAIN_BATCH", "8"))
    gate = float(_param("map50_gate", "POSE_MAP50_GATE", str(MAP50_GATE)))
    print(f"🚂 開始訓練：epochs={epochs} batch={batch} device={device} "
          f"門檻 pose mAP50≥{gate}")
    model.train(
        data=data_yaml,
        epochs=epochs,
        imgsz=640,
        batch=batch,
        device=device,
        plots=False,     # 關掉大圖生成/上傳，省頻寬也避開 ClearML 上傳大圖的相容問題
        patience=20,     # early-stop：連續 20 epoch 沒進步就停，防小資料過擬
        project="runs/pose",
        name="train",
        exist_ok=True,
    )

    # ── 評估 ────────────────────────────────────────────────────────────────
    # 主動 val 一次而不是只信 ClearML 的自動 hook：欄位名不保證抓得到，而且 val 集是
    # prepare_dataset.py 切出來、**沒有參與訓練**的那 20%，這才是能對門檻的數字。
    pose_map50 = box_map50 = None
    try:
        metrics = model.val(data=data_yaml, imgsz=640, device=device)
        pose_map50 = float(metrics.pose.map50)
        box_map50 = float(metrics.box.map50)
        print(f"📊 pose mAP50={pose_map50:.4f}  box mAP50={box_map50:.4f}"
              f"（門檻看 pose，≥ {gate}）")
        logger = task.get_logger()
        logger.report_single_value("pose_mAP50", pose_map50)
        logger.report_single_value("box_mAP50", box_map50)
        logger.report_single_value("pose_mAP50_gate", gate)
        print("✅ 達到門檻" if pose_map50 >= gate else
              "⚠️ 未達門檻 —— 數字照實記錄，權重照樣上傳，只是不標 best")
    except Exception as e:
        print(f"⚠️ 訓後評估 model.val() 失敗（{e}），mAP 請看 ClearML 自動記錄的 scalar")

    if pose_map50 is not None:
        task.set_parameters_as_dict({"metrics": {
            "pose_mAP50": pose_map50, "box_mAP50": box_map50,
        }})

    # ── 產出模型並標籤 ──────────────────────────────────────────────────────
    # 兩道關卡都要過才標 best：
    #   1. 過絕對門檻（gate）——不然一顆爛模型會被熱部署撿去上線
    #   2. 不比上一輪差（打擂台）——不然滾動式重訓會一輪一輪往下掉
    # ⚠️ 上游只有第 2 關而且是「>=」無條件標 best，冷啟動那輪 old_map50=0，
    #    任何垃圾都會過。實測在 RT-DETR 那條踩過：一輪 1 epoch 的 sanity 模型
    #    （mAP50=0.0207）被標成 best，排在正式那輪（0.9912）前面。
    passed_gate = pose_map50 is not None and pose_map50 >= gate
    beat_champion = pose_map50 is not None and pose_map50 >= old_map50
    passed = passed_gate and beat_champion

    map_tag = f"map50_{pose_map50:.4f}" if pose_map50 is not None else "map50_unknown"
    tags = (MODEL_TAGS_BEST if passed else MODEL_TAGS_REJECT) + [map_tag]
    if passed:
        reason = f"標記 best（pose mAP50={pose_map50:.4f} ≥ 門檻 {gate} 且不低於上一輪 {old_map50:.4f}）"
    elif not passed_gate:
        reason = f"標記 below-gate（pose mAP50={pose_map50} 未過門檻 {gate}）"
    else:
        reason = f"標記 below-gate（pose mAP50={pose_map50:.4f} 低於上一輪 {old_map50:.4f}，退步了）"

    models = task.get_models() or {}
    outputs = models.get("output") or []
    # ⚠️ 不能用 outputs[-1]（上游的做法）。ClearML 會把**輸入**的 yolo11s-pose.pt 也
    # 登記成這個 task 的模型，清單裡混著「這輪訓出來的 best.pt」與「拿來繼承的起始權重」，
    # 位置不保證。標到起始權重上，等於自動流程永遠撿不到真正訓出來的模型。
    out = next((m for m in reversed(outputs)
                if str(getattr(m, "url", "")).endswith("best.pt")), None) \
        or (outputs[-1] if outputs else None)
    if out is None:
        # ClearML 沒自動抓到就手動補一次，並強制指定 S3 目的地
        local_best = os.path.join("runs", "pose", "train", "weights", "best.pt")
        if not os.path.exists(local_best):
            print("⚠️ 找不到任何產出的權重，檢查訓練是否正常結束")
            notify("❌ 【YOLO-Pose 重訓失敗】", "找不到產出的權重，請看 ClearML log。", 15548997)
            return 1
        out = OutputModel(task=task, name=TASK_NAME, destination=S3_OUTPUT_URI)
        out.update_weights(weights_filename=local_best, auto_delete_local_copy=False)

    out.tags = tags
    verify = Model(model_id=out.id).tags
    print(f"✅ 權重已上傳 S3 並{reason}（model={out.id[:8]} 讀回 tags={verify}）")
    if set(verify) != set(tags):
        print(f"⚠️ 標籤沒有落地（預期 {tags} 實得 {verify}）—— 自動流程會撿不到這顆，請手動處理")

    if passed:
        notify("🎉 【YOLO-Pose 重訓過關：可自動部署】",
               f"**pose mAP50**：`{pose_map50:.4f}`（上一輪 `{old_map50:.4f}`，門檻 `{gate}`）\n"
               f"**狀態**：已標記 `best`，等 model_deployment_agent 熱部署。\n"
               f"**Task**：`{task.id}`", 5763719)
    else:
        notify("⚠️ 【YOLO-Pose 重訓未過關：已阻擋部署】",
               f"**pose mAP50**：`{pose_map50}`（上一輪 `{old_map50:.4f}`，門檻 `{gate}`）\n"
               f"**狀態**：標記 `below-gate`，維持原模型運作。\n"
               f"**Task**：`{task.id}`", 15548997)
    return 0


if __name__ == "__main__":
    sys.exit(main())

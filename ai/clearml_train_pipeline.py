#!/usr/bin/env python3
"""RT-DETR 滾動式重訓：繼承上一輪的 best、訓練、評估 mAP、把權重推上 S3 標記 best。

移植自 `origin/albert_chiang:Fall/tools/clearml_train_pipeline.py`，並收掉本機那份
未進版控的 `clearml_train_pipeline_final.py`（151 行、第 8/78/94 行寫死
`/home/rapubuntu/...`）—— 那支其實是 `submit_task.py` 產生的**機器產物**，不是原始碼，
所以它才會有硬路徑。原始碼在這裡，產物已進 .gitignore。

## 它在整條迴路的位置

    Label Studio 人工 Submit → webhook_receiver(9001) → submit_task.py 排隊
                                                              │
                                              clearml-agent 咬單，執行這支
                                                              │
                            繼承雲端 best.pt → 訓練 → 評估 mAP → 上傳 S3 標 best
                                                              │
                                              model_deployment_agent.py 熱部署進 Triton

## 硬路徑怎麼解掉的（上游最大的坑）

ClearML agent 是把腳本複製到它自己的暫存目錄執行的，`__file__` 指到暫存路徑，
所以腳本**找不到 repo 裡的 data.yaml**——上游就是因此把絕對路徑寫死在原始碼裡。
這裡改成：`submit_task.py` 在排隊時把「repo 的 ai/ 在哪」當成 **Task 參數**傳進來
（值是它自己 `__file__` 算出來的），這支再從 Task 參數讀回。
絕對路徑變成執行時的設定值、不是原始碼裡的字面值 —— 換一台機器由那台的
`submit_task.py` 自己算，護欄也不會擋。直接手動執行時則退回 `__file__` 基準。

直接跑（不經 ClearML agent，除錯用）：
    python ai/clearml_train_pipeline.py
    TRAIN_EPOCHS=50 python ai/clearml_train_pipeline.py
"""
import os
import sys

# ── 定位 repo 的 ai/ ─────────────────────────────────────────────────────────
# agent 執行時 __file__ 在暫存目錄，所以優先看 submit_task 傳進來的參數/環境變數。
_AI_DIR = os.environ.get("AIPE03_AI_DIR") or os.path.dirname(os.path.abspath(__file__))

from clearml import Model, OutputModel, Task  # noqa: E402

# Task 參數要在 Task.init 之後才拿得到，先用環境變數頂著；下面 main() 會再校正一次。
PROJECT_NAME = os.environ.get("CLEARML_PROJECT", "Fall_Detection")
TASK_NAME = os.environ.get("CLEARML_TASK_NAME", "RTDETR_Cloud_Incremental_Training")

# 模型權重的雲端落點。bucket 走環境變數，未設時退回 aipe03-3（與本機 bucket 同名）。
S3_BUCKET = os.environ.get("AWS_BUCKET_NAME", "aipe03-3")
S3_OUTPUT_URI = f"s3://{S3_BUCKET}/clearml-artifacts/models/fall_detection/"

# 會議訂的驗收門檻：mAP50 ≥ 0.80（80~90%）。只用來判定「這輪要不要放行部署」，
# 訓練本身照樣跑完、數字照樣記，不會因為沒過就不留紀錄。
MAP50_GATE = float(os.environ.get("MAP50_GATE", "0.80"))


def _bootstrap_paths() -> str:
    """把 repo 的 ai/ 放進 sys.path 並回傳它，讓 mlops_paths 之類的同伴模組 import 得到。"""
    if _AI_DIR not in sys.path:
        sys.path.insert(0, _AI_DIR)
    return _AI_DIR


def _resolve_data_yaml() -> str:
    """取得含絕對路徑的 data.yaml。

    優先用 `mlops_paths.resolve_data_yaml()`；agent 只複製單一腳本、import 不到同伴
    模組時，退回在這裡自己展開一次（邏輯與那支相同，刻意重複以保持 standalone 可執行）。
    """
    try:
        from mlops_paths import resolve_data_yaml
        return resolve_data_yaml()
    except ImportError:
        import yaml
        src = os.path.join(_AI_DIR, "data.yaml")
        with open(src, encoding="utf-8") as f:
            spec = yaml.safe_load(f)
        base = spec.get("path", ".")
        base = base if os.path.isabs(base) else os.path.normpath(os.path.join(_AI_DIR, base))
        spec["path"] = base
        for k in ("train", "val", "test"):
            if spec.get(k) and not os.path.isabs(spec[k]):
                spec[k] = os.path.normpath(os.path.join(base, spec[k]))
        dst = os.path.join(_AI_DIR, "data.runtime.yaml")
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


def pick_base_weights() -> str:
    """滾動式重訓的核心：先找雲端上一輪標了 best 的權重來繼承，沒有才冷啟動。"""
    fallback = os.path.join(_AI_DIR, "rtdetr-l.pt")
    fallback = fallback if os.path.exists(fallback) else "rtdetr-l.pt"
    try:
        print("🔍 檢查雲端有沒有上一輪產出的 best 模型 ...")
        found = Model.query_models(project_name=PROJECT_NAME, tags=["best"])
        if not found:
            print(f"ℹ️ 雲端還沒有任何 best 模型，本輪從 {fallback} 冷啟動")
            return fallback
        latest = sorted(found, key=_model_created, reverse=True)[0]
        print(f"📥 找到上一輪的最新模型（id={latest.id}），拉權重下來繼承")
        local = latest.get_local_copy()
        if local and os.path.exists(local):
            print("🔄 繼承成功，這輪在它的基礎上繼續訓練")
            return local
        print("⚠️ 權重下載不到，降級冷啟動")
    except Exception as e:
        print(f"⚠️ 查詢雲端 best 失敗（{e}），降級用 {fallback} 冷啟動")
    return fallback


def main() -> int:
    _bootstrap_paths()

    task = Task.init(project_name=PROJECT_NAME, task_name=TASK_NAME)

    # submit_task 把 ai/ 位置與超參數都放在 Task 參數裡，agent 執行時從這裡讀回來。
    # ⚠️ 不能改讀環境變數：agent 是另一個行程，不會繼承排隊端的 os.environ
    #    （實測踩過：排隊端設 TRAIN_EPOCHS=60，agent 這端印的是 epochs=1）。
    #    環境變數只留給「直接手動執行這支」的除錯情境當 fallback。
    params = task.get_parameters() or {}

    def _param(name: str, env: str, default: str) -> str:
        return (params.get(f"General/{name}") or params.get(name)
                or os.environ.get(env) or default)

    ai_dir = params.get("General/ai_dir") or params.get("ai_dir")
    if ai_dir and os.path.isdir(ai_dir):
        globals()["_AI_DIR"] = ai_dir
        _bootstrap_paths()
        print(f"📁 由 Task 參數取得 ai/ 位置：{ai_dir}")

    # submit_task 為了繞過本地憑證檢查會把 output_uri 設成別的，agent 接手後扳回 S3
    task.output_uri = S3_OUTPUT_URI

    data_yaml = _resolve_data_yaml()
    print(f"📚 資料集定義：{data_yaml}")

    from ultralytics import RTDETR
    model = RTDETR(pick_base_weights())

    epochs = int(_param("epochs", "TRAIN_EPOCHS", "60"))
    device = _param("device", "TRAIN_DEVICE", "0")   # 這台是 RTX 5060 Ti，走 GPU
    batch = int(_param("batch", "TRAIN_BATCH", "4"))
    gate = float(_param("map50_gate", "MAP50_GATE", str(MAP50_GATE)))
    print(f"🚂 開始訓練：epochs={epochs} batch={batch} device={device} 門檻 mAP50≥{gate}")
    model.train(
        data=data_yaml,
        epochs=epochs,
        imgsz=640,
        batch=batch,
        device=device,
        plots=False,     # 關掉大圖生成/上傳，省頻寬也避開 ClearML 上傳大圖的相容問題
        patience=20,     # early-stop：連續 20 epoch 沒進步就停，防小資料過擬
    )

    # ── 評估：一定要主動 val 一次並印出來 ──────────────────────────────────
    # 不能只靠 ClearML 的自動 hook：欄位名不保證抓得到，而且 val 集是
    # ai/prepare_dataset.py 切出來、**沒有參與訓練**的那 20%，這才是可以拿來對門檻的數字。
    map50 = map5095 = None
    try:
        metrics = model.val(data=data_yaml, imgsz=640, device=device)
        map50, map5095 = float(metrics.box.map50), float(metrics.box.map)
        print(f"📊 mAP50={map50:.4f}  mAP50-95={map5095:.4f}（門檻 mAP50 ≥ {gate}）")
        logger = task.get_logger()
        logger.report_single_value("mAP50", map50)
        logger.report_single_value("mAP50-95", map5095)
        logger.report_single_value("mAP50_gate", gate)
        print("✅ 達到門檻" if map50 >= gate else
              "⚠️ 未達門檻 —— 數字照實記錄，是否部署由 model_deployment_agent.py 決定")
    except Exception as e:
        print(f"⚠️ 訓後評估 model.val() 失敗（{e}），mAP 請看 ClearML 自動記錄的 scalar")

    # 讓部署端不必自己重算：把這輪的成績掛成 Task 參數，model_deployment_agent 讀它擋門檻
    if map50 is not None:
        task.set_parameters_as_dict({"metrics": {"mAP50": map50, "mAP50-95": map5095}})

    # ── 產出模型並標 best ────────────────────────────────────────────────────
    # ⚠️ **只有過門檻才標 best**。上游是每一輪都無條件標 best，那會出兩件事：
    #   1. 下一輪的「繼承上一輪最強大腦」會去繼承一個更差的模型；
    #   2. model_deployment_agent 抓「最新的 best」會抓到那個更差的模型直接上線。
    # 兩者都不會報錯，只會讓模型一輪一輪變差。實測踩過：一輪 sanity 用的 1 epoch
    # （mAP50=0.0207）被標成 best 之後，就排在正式那輪（mAP50=0.9912）前面了。
    # 沒過門檻的照樣上傳、照樣留紀錄，只是改標 below-gate，不會被自動流程撿走。
    passed = map50 is not None and map50 >= gate
    tags = ["best"] if passed else ["below-gate"]
    tag_note = ("標記 best" if passed else
                f"標記 below-gate（mAP50={map50} 未過門檻 {gate}，不讓自動流程撿走）")

    models = task.get_models() or {}
    outputs = models.get("output") or []
    # ⚠️ 不能用 outputs[-1]（上游的做法）。ClearML 會把**輸入**的 rtdetr-l.pt 也登記成
    # 這個 task 的模型，所以清單裡混著「這輪訓出來的 best.pt」與「拿來繼承的起始權重」，
    # 位置不保證。實測踩過：100 epoch 那輪印了「已標記 best」，但事後查那顆
    # mAP50=0.9912 的模型 tags 是空的 —— 標籤標到別的物件上，
    # 於是自動流程只看得到兩顆 1 epoch 的 sanity 模型。
    # 改成明確挑「這個 task 上傳的 best.pt」，標完再讀回來確認。
    out = next((m for m in reversed(outputs)
                if str(getattr(m, "url", "")).endswith("best.pt")), None) \
        or (outputs[-1] if outputs else None)
    if out is not None:
        out.tags = tags
        verify = Model(model_id=out.id).tags
        print(f"✅ 權重已上傳 S3 並{tag_note}（model={out.id[:8]} 讀回 tags={verify}）")
        if set(verify) != set(tags):
            print(f"⚠️ 標籤沒有落地（預期 {tags} 實得 {verify}）—— "
                  f"自動流程會撿不到這顆，請手動處理")
    else:
        # ClearML 沒自動抓到就手動補一次，並強制指定 S3 目的地
        local_best = os.path.join("runs", "detect", "train", "weights", "best.pt")
        if os.path.exists(local_best):
            out = OutputModel(task=task, name=TASK_NAME, destination=S3_OUTPUT_URI)
            out.update_weights(weights_filename=local_best, auto_delete_local_copy=False)
            out.tags = tags
            print(f"✅ 已手動把 {local_best} 推上 S3 並{tag_note}")
        else:
            print("⚠️ 找不到任何產出的權重，檢查訓練是否正常結束")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

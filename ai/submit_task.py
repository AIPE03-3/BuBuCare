#!/usr/bin/env python3
"""把重訓任務排進 ClearML 佇列，讓 clearml-agent 在背景咬單執行。

移植自 `origin/albert_chiang:Fall/tools/submit_task.py`（99 行）。
被 `ai/webhook_receiver.py` 呼叫（Label Studio 標註量到門檻時自動點火），也可以手動跑。

## 與上游的三處差異

1. **不再產生 `clearml_train_pipeline_final.py`**。上游會把「自動 pip install + 讀 .env
   塞 os.environ」的前置碼串在訓練腳本前面，寫成一個新檔再上傳。這台本機已經有
   `ai/.venv` 裝好全部相依，agent 用 `CLEARML_AGENT_SKIP_PIP_VENV_INSTALL` 直接沿用，
   不需要每次重裝。那支產物就是目前未進版控、又寫死家目錄路徑的 151 行檔的來源
   —— 移除產生它的機制，問題從根拔掉。
2. **repo 位置改用 Task 參數傳遞**。agent 是把腳本複製到暫存目錄執行的，`__file__`
   指到暫存路徑、找不到 repo 裡的 `data.yaml`；上游因此把絕對路徑寫死在訓練腳本裡。
   改成排隊時把 `ai/` 的位置（由這支自己的 `__file__` 算出）當成 Task 參數傳過去，
   絕對路徑變成執行時的設定值而非原始碼字面值，換機器由該機自己算，護欄也不會擋。
3. **憑證改走 `mlops_paths`**（真實環境變數優先於 repo 根目錄 `.env`），不再自己
   開檔 parse `ai/.env`，也不再把整份 .env 倒進 os.environ。

## 上游那段「先刪掉 AWS_* 環境變數」為什麼保留

排隊階段（本機這支）如果帶著 AWS 憑證，ClearML SDK 會在建立 Task 時就去驗 S3 權限，
本機憑證有問題時整個排隊會失敗。真正要寫 S3 的是 agent 那端（訓練腳本自己會設
output_uri）。所以這裡刻意在排隊前清掉，讓排隊這一步跟 S3 完全無關。

## 兩條重訓線共用這支

`--task detect`（預設）排 RT-DETR、`--task pose` 排 YOLO-Pose。兩者的差別只是「排哪支
腳本、叫什麼任務名、超參數預設值」，排隊機制完全一樣，所以不另開一支檔——
上游是每條線各一支 submit，改一次排隊邏輯要記得改兩個地方。

⚠️ `TASKS` 裡的 `device` 預設值刻意不同：RT-DETR 固定跑 5060 Ti（`"0"`），
YOLO-Pose 用 `"auto"`（cuda → mps → cpu），因為骨架重訓在 Mac 本機也要跑得起來。

用法：
    python ai/submit_task.py                  # 排 RT-DETR 重訓（已有進行中的就跳過）
    python ai/submit_task.py --task pose      # 排 YOLO-Pose 重訓
    python ai/submit_task.py --force          # 就算已有進行中的也再排一張
"""
import argparse
import os
import sys

from mlops_paths import AI_DIR

# ⚠️ 順序重要：要在 import clearml 之前清掉（見檔頭說明）
for _k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
           "AWS_SESSION_TOKEN", "AWS_DEFAULT_REGION"):
    os.environ.pop(_k, None)

# 禁掉 agent 自帶的 git 偵測：這支腳本是以 standalone script 上傳的，
# 讓它去比對 repo 的 commit 狀態只會在「地端有未 commit 的改動」時報錯。
os.environ["CLEARML_DISABLE_GIT_DETECTION"] = "1"

from clearml import Task  # noqa: E402

PROJECT_NAME = os.environ.get("CLEARML_PROJECT", "Fall_Detection")
QUEUE_NAME = os.environ.get("CLEARML_QUEUE", "default")

# 兩條重訓線的差異全部收在這張表裡，排隊邏輯只有一份。
TASKS = {
    "detect": {
        "task_name": os.environ.get(
            "CLEARML_TASK_NAME", "RTDETR_Cloud_Incremental_Training"),
        "script": os.path.join(AI_DIR, "clearml_train_pipeline.py"),
        "gate_env": "MAP50_GATE",
        "defaults": {"epochs": "60", "batch": "4", "device": "0", "gate": "0.80"},
    },
    "pose": {
        "task_name": os.environ.get(
            "CLEARML_POSE_TASK_NAME", "YOLOPose_Cloud_Incremental_Training"),
        "script": os.path.join(AI_DIR, "clearml_pose_train_pipeline.py"),
        "gate_env": "POSE_MAP50_GATE",
        # device=auto：cuda → mps → cpu，讓骨架重訓在 Mac 本機也跑得起來
        "defaults": {"epochs": "60", "batch": "8", "device": "auto", "gate": "0.80"},
    },
}


def submit(force: bool = False, task_kind: str = "detect") -> int:
    """排一張重訓單。`ai/webhook_receiver.py` 直接呼叫這支（不要呼叫 main()，
    那支會去 parse sys.argv —— 在 uvicorn 行程裡拿到的是 uvicorn 的參數）。

    `task_kind` 有預設值，既有呼叫端（webhook_receiver 傳的是 `force=`）不受影響。
    """
    spec = TASKS.get(task_kind)
    if spec is None:
        sys.exit(f"❌ 不認得的重訓類型：{task_kind}（可用：{', '.join(TASKS)}）")
    pipeline, task_name = spec["script"], spec["task_name"]
    if not os.path.exists(pipeline):
        sys.exit(f"❌ 找不到訓練腳本：{pipeline}")

    if not force:
        # ⚠️ 比對的是**這條線的**任務名。兩條線同時在跑是正常的，用專案名去擋會
        #    讓 pose 因為 RT-DETR 還在跑而被跳過。
        active = Task.get_tasks(project_name=PROJECT_NAME, task_name=task_name,
                                task_filter={"status": ["in_progress", "queued"]})
        if active:
            print(f"🛑 已有任務 {active[0].id}（{task_name}）在執行/排隊中，跳過重複點火"
                  f"（要強制再排一張加 --force）")
            return 0

    task = Task.create(
        project_name=PROJECT_NAME,
        task_name=task_name,
        task_type="training",
        script=pipeline,
        detect_repository=False,   # 以純 standalone 腳本上傳，不綁 git 狀態
    )
    # ⚠️ 超參數一定要走 Task 參數，不能靠環境變數。
    # agent 是另一個行程、而且通常在另一台機器上，**不會繼承排隊端的 os.environ**。
    # 實測踩過：`TRAIN_EPOCHS=60 python ai/submit_task.py` 排出去的任務，agent 那端
    # 印的是 `開始訓練：epochs=1` —— 訓練照跑、完全不報錯，只是跑的不是你要的設定。
    # 放進 Task 參數還有兩個好處：ClearML web 上看得到這次用什麼超參數跑的，
    # 以及可以在 web 上 clone 任務改參數重跑。
    d = spec["defaults"]
    task.set_parameters({
        # repo 位置：讓訓練腳本在 agent 的暫存目錄裡也找得到（見檔頭第 2 點）
        "ai_dir": AI_DIR,
        "epochs": os.environ.get("TRAIN_EPOCHS", d["epochs"]),
        "batch": os.environ.get("TRAIN_BATCH", d["batch"]),
        "device": os.environ.get("TRAIN_DEVICE", d["device"]),
        "map50_gate": os.environ.get(spec["gate_env"], d["gate"]),
    })
    task.set_base_docker(None)
    task.set_packages([])          # 不讓 agent 自行裝套件，沿用本機 ai/.venv
    task.output_uri = True

    print(f"📦 任務建立成功：{task.id}（{task_kind} / {task_name}）")
    Task.enqueue(task=task, queue_name=QUEUE_NAME)
    print(f"✅ 已進入佇列 '{QUEUE_NAME}'，等 clearml-agent 咬單")
    print(f"   看進度： http://localhost:8085/projects/*/experiments/{task.id}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="把重訓任務排進 ClearML 佇列")
    ap.add_argument("--task", choices=tuple(TASKS), default="detect",
                    help="detect＝RT-DETR 物件偵測（預設）；pose＝YOLO-Pose 人體骨架")
    ap.add_argument("--force", action="store_true",
                    help="即使已有進行中/排隊中的同名任務也照排（預設會跳過）")
    args = ap.parse_args()
    return submit(force=args.force, task_kind=args.task)


if __name__ == "__main__":
    sys.exit(main())

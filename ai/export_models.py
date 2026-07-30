#!/usr/bin/env python3
"""把本機的模型權重匯出成 Triton 吃得下的格式，重建 `ai/triton_repo/`。

為什麼需要這支：模型本體（`.onnx` / `.plan`，合計約 240MB）**不進 repo**
（見 `.gitignore` 與 `ai/triton_repo/README.md`），clone 下來只有 `config.pbtxt`。
docs/CONTRIBUTING.md、`ai/run_triton.sh`、`scripts/check_guardrails.py` 三處都叫人跑
`python ai/export_models.py` 重建 —— 但這支檔以前根本不存在，那條路徑是斷的。

三顆模型與各自的來源權重（都在 `ai/` 底下，`.pt`/`.pth` 同樣不進 repo）：

| Triton 模型 | 來源 | 產出 | 形狀 |
|---|---|---|---|
| `yolo_pose` | `yolo11s-pose.pt` | `1/model.onnx` | 動態 batch/H/W |
| `rt_detr` | `rtdetr-l.pt` | `1/model.onnx`（+ `--plan` 產 `1/model.plan`）| 固定 [1,3,640,640] |
| `action_transformer` | `action_transformer.pth` | `1/model.onnx` | 固定 [1,30,34] |

**形狀不是隨便選的**：每顆都必須對上已進版控的 `config.pbtxt`，對不上 Triton 會拒載。
所以這支的匯出參數是「照著現行 config 反推」，不是照上游預設值抄。

⚠️ `rt_detr` 在這台是 `platform: tensorrt_plan`，**只有 `model.onnx` 起不來**，
一定要再跑 `--plan` 編出 Blackwell 專屬的 TensorRT 引擎（見 `triton_repo/README.md`
的 2026-07-26 事故記錄：缺 `.plan` 會讓整支 Triton 連另外兩顆一起倒）。

用法：
    python ai/export_models.py                  # 三顆 ONNX 都匯出（已存在的跳過）
    python ai/export_models.py --plan           # 順便編 rt_detr 的 TensorRT 引擎
    python ai/export_models.py --only rt_detr --version 2 --plan --force
    python ai/export_models.py --plan-only --version 2   # 只編引擎，不重匯 ONNX

預設**不覆蓋**已存在的檔案（`rt_detr/1/model.plan` 是全組唯一一份能用的 Blackwell
引擎，重建一次要好幾分鐘），要覆蓋請明講 `--force`。
"""
import argparse
import os
import shutil
import subprocess
import sys

_AI_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_DIR = os.path.join(_AI_DIR, "triton_repo")

# 與 ai/run_triton.sh 同一個預設鏡像：編引擎要用「跟上線同一版」的 TensorRT，
# 不同版編出來的 plan 不保證載得進去（plan 綁 TensorRT 版本 + GPU 架構）。
TRITON_IMAGE = os.environ.get("TRITON_IMAGE", "nvcr.io/nvidia/tritonserver:25.10-py3")

IMGSZ = 640


# ── ActionTransformer ────────────────────────────────────────────────────────
# ⚠️ 這份結構必須與 ai/inference_test.py:390-402 的 ActionTransformer **逐字一致**，
# 那裡才是唯一真相。這裡重抄一份而不是 import，是因為 inference_test.py 一被 import
# 就會去連 Triton / Kafka（模組層級就在建 client），匯出腳本不該有那些副作用。
# 改動那邊的結構時，這裡要跟著改，否則 load_state_dict 會直接噴 key 不符。
def _build_action_transformer():
    import torch.nn as nn

    class ActionTransformer(nn.Module):
        def __init__(self, input_dim=34, seq_len=30, num_classes=2):
            super(ActionTransformer, self).__init__()
            self.embedding = nn.Linear(input_dim, 64)
            encoder_layer = nn.TransformerEncoderLayer(
                d_model=64, nhead=4, dim_feedforward=128, batch_first=True
            )
            self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=2)
            self.fc = nn.Sequential(
                nn.Linear(64, 32), nn.ReLU(), nn.Linear(32, num_classes)
            )

        def forward(self, x):
            x = self.embedding(x)
            x = self.transformer(x)
            return self.fc(x.mean(dim=1))

    return ActionTransformer()


# ── 共用小工具 ───────────────────────────────────────────────────────────────
def _version_dir(model: str, version: int) -> str:
    return os.path.join(_REPO_DIR, model, str(version))


def _target(model: str, version: int, filename: str) -> str:
    return os.path.join(_version_dir(model, version), filename)


def _should_skip(path: str, force: bool) -> bool:
    if os.path.exists(path) and not force:
        size_mb = os.path.getsize(path) / 1024 / 1024
        print(f"⏭️  已存在，跳過：{os.path.relpath(path, _AI_DIR)}（{size_mb:.1f}MB）"
              f"—— 要重建請加 --force")
        return True
    return False


def _place(src: str, dst: str) -> None:
    """把匯出結果搬到 Triton 版本目錄，並印出大小。"""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        # 既有檔可能是容器內 root 建立的（trtexec 產物），先試著移除並給出可讀的錯誤
        try:
            os.remove(dst)
        except PermissionError:
            sys.exit(
                f"❌ 無法覆蓋 {dst}（權限不足）。\n"
                f"   這通常是舊檔由容器內 root 建立造成的。先手動移除：\n"
                f"     sudo rm {dst}"
            )
    shutil.move(src, dst)
    print(f"✅ {os.path.relpath(dst, _AI_DIR)}（{os.path.getsize(dst) / 1024 / 1024:.1f}MB）")


def _report_onnx(path: str) -> None:
    """印出 ir_version / opset / 輸入輸出形狀，方便和 config.pbtxt 對帳。"""
    try:
        import onnx
    except ImportError:
        return
    m = onnx.load(path, load_external_data=False)

    def shape(v):
        return [d.dim_value or d.dim_param for d in v.type.tensor_type.shape.dim]

    ops = ", ".join(f"{o.domain or 'ai.onnx'}={o.version}" for o in m.opset_import)
    print(f"   ir_version={m.ir_version}  opset={ops}")
    for i in m.graph.input:
        print(f"   input  {i.name}: {shape(i)}")
    for o in m.graph.output:
        print(f"   output {o.name}: {shape(o)}")


# ── 三顆模型的匯出 ───────────────────────────────────────────────────────────
def export_yolo_pose(version: int, force: bool) -> bool:
    dst = _target("yolo_pose", version, "model.onnx")
    if _should_skip(dst, force):
        return True
    src_pt = os.path.join(_AI_DIR, "yolo11s-pose.pt")
    if not os.path.exists(src_pt):
        print(f"❌ 找不到來源權重：{os.path.relpath(src_pt, _AI_DIR)}（要跟組員拿）")
        return False

    print("── yolo_pose ← yolo11s-pose.pt ──")
    from ultralytics import YOLO

    # dynamic=True：對上 config.pbtxt 的 dims [-1, 3, -1, -1] / [-1, 56, -1]。
    # 這顆刻意留動態尺寸，triton_pose_client 才能直接餵原圖不必先 letterbox 到 640。
    out = YOLO(src_pt).export(format="onnx", dynamic=True)
    _place(out, dst)
    _report_onnx(dst)
    return True


def export_rt_detr(version: int, force: bool) -> bool:
    dst = _target("rt_detr", version, "model.onnx")
    if _should_skip(dst, force):
        return True
    src_pt = os.path.join(_AI_DIR, "rtdetr-l.pt")
    if not os.path.exists(src_pt):
        print(f"❌ 找不到來源權重：{os.path.relpath(src_pt, _AI_DIR)}"
              f"（首次執行 ultralytics 會自動下載，需要網路）")
        return False

    print("── rt_detr ← rtdetr-l.pt ──")
    from ultralytics import RTDETR

    # 固定 [1,3,640,640] + opset 16：對上 config.pbtxt 的 dims [1,3,640,640]，
    # 也是 TensorRT 編引擎最省事的形式（固定 shape 不必給 optimization profile）。
    out = RTDETR(src_pt).export(format="onnx", imgsz=IMGSZ, opset=16, dynamic=False)
    _place(out, dst)
    _report_onnx(dst)
    return True


def export_action_transformer(version: int, force: bool) -> bool:
    dst = _target("action_transformer", version, "model.onnx")
    if _should_skip(dst, force):
        return True
    src_pth = os.path.join(_AI_DIR, "action_transformer.pth")
    if not os.path.exists(src_pth):
        print(f"⚠️  找不到 {os.path.relpath(src_pth, _AI_DIR)} —— 略過這顆。"
              f"（Triton 照樣起得來，inference_test 會退回模擬機制，見 run_triton.sh）")
        return True

    print("── action_transformer ← action_transformer.pth ──")
    import torch

    model = _build_action_transformer()
    model.load_state_dict(torch.load(src_pth, map_location="cpu"))
    model.eval()

    tmp = os.path.join(_AI_DIR, "_act_export.onnx")
    # ⚠️ 這裡刻意**不給 dynamic_axes**（上游 Albert 的版本有給 batch 動態軸）：
    # 本專案的 config.pbtxt 寫死 dims [1,30,34] / [1,2]，模型若是動態 batch 會與 config
    # 對不上，Triton 直接拒載。AcT 本來就是一次一個 30 幀視窗，不需要 batch。
    torch.onnx.export(
        model,
        torch.randn(1, 30, 34, dtype=torch.float32),
        tmp,
        input_names=["input"],
        output_names=["output"],
        opset_version=17,
        dynamo=False,   # 走傳統 exporter：新版 torch 預設的 dynamo 匯出器會改變圖結構
    )

    # 把 IR version 壓回 8，對齊現行已驗證可載入的產物（上游降級是為了 Triton 23.10，
    # 這台是 25.10，但沿用同一個值可保證與線上那份位元語意一致，沒有理由冒險換）。
    import onnx
    m = onnx.load(tmp)
    m.ir_version = 8
    onnx.save(m, tmp)

    _place(tmp, dst)
    _report_onnx(dst)
    return True


# ── TensorRT 引擎 ────────────────────────────────────────────────────────────
def build_rt_detr_plan(version: int, force: bool) -> bool:
    """用 Triton 官方鏡像內的 trtexec 把 rt_detr 的 ONNX 編成 TensorRT 引擎。

    為什麼要另外開一個容器而不是 `docker exec nh-triton`：
      1. 不必假設 nh-triton 正在跑，也不必去猜它把 model repo 掛在容器內哪個路徑；
      2. 編引擎很吃 GPU 記憶體，跟正在服務的 server 搶資源不是好主意。
    用 `--user` 帶自己的 uid/gid，產出的 .plan 才不會變成 root 所有（上一版就是這樣，
    導致之後要覆蓋時 Permission denied）。
    """
    onnx_path = _target("rt_detr", version, "model.onnx")
    plan_path = _target("rt_detr", version, "model.plan")
    if not os.path.exists(onnx_path):
        print(f"❌ 缺 {os.path.relpath(onnx_path, _AI_DIR)}，先跑一次不帶 --plan-only 的匯出")
        return False
    if _should_skip(plan_path, force):
        return True

    print(f"── rt_detr TensorRT 引擎（v{version}，FP16）──")
    print("   這一步會跑幾分鐘，trtexec 會逐層試 tactic，慢是正常的")

    # 舊檔一定要先刪掉再編。trtexec 是以 --user 指定的 uid 在容器內開檔，舊 .plan 若是
    # 更早以前由容器內 root 產生的，開來寫會失敗 —— 而且它是「跑完 4 分鐘的編譯之後」
    # 才在存檔那一刻炸（Cannot write to FileStreamWriter → Attempting to access an empty
    # engine!），非常浪費時間。刪檔看的是目錄權限不是檔案擁有者，所以這裡刪得掉。
    # 對正在服務的 Triton 無影響：它已經把引擎讀進記憶體，unlink 不會動到那份。
    if os.path.exists(plan_path):
        try:
            os.remove(plan_path)
        except PermissionError:
            print(f"❌ 無法移除舊的 {os.path.relpath(plan_path, _AI_DIR)}（權限不足）\n"
                  f"   先手動移除再重跑： sudo rm {plan_path}")
            return False

    uid_gid = f"{os.getuid()}:{os.getgid()}"
    cmd = [
        "docker", "run", "--rm", "--gpus", "all", "--user", uid_gid,
        "-v", f"{_REPO_DIR}:/models",
        TRITON_IMAGE,
        "/usr/src/tensorrt/bin/trtexec",
        f"--onnx=/models/rt_detr/{version}/model.onnx",
        f"--saveEngine=/models/rt_detr/{version}/model.plan",
        "--fp16",
    ]
    print("   " + " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.exists(plan_path):
        print("❌ trtexec 失敗，尾段輸出：")
        print("\n".join((proc.stderr or proc.stdout).strip().split("\n")[-20:]))
        return False

    size_mb = os.path.getsize(plan_path) / 1024 / 1024
    print(f"✅ triton_repo/rt_detr/{version}/model.plan（{size_mb:.1f}MB）")
    for line in proc.stdout.split("\n"):
        if "Throughput" in line or "Latency: min" in line or "GPU Compute Time: min" in line:
            print("   " + line.strip())
    print("⚠️  這份引擎綁這台的 GPU 架構（Blackwell sm_120）與 TensorRT 版本，"
          "換機器不能直接複製，要在該機重編。")
    return True


EXPORTERS = {
    "yolo_pose": export_yolo_pose,
    "rt_detr": export_rt_detr,
    "action_transformer": export_action_transformer,
}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="重建 ai/triton_repo/ 底下的模型檔（ONNX / TensorRT plan）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--only", choices=sorted(EXPORTERS), action="append",
                    help="只匯出指定模型（可重複給）；未給＝三顆都做")
    ap.add_argument("--version", type=int, default=1,
                    help="寫進哪個版本目錄（預設 1）。要熱部署新版時給 2")
    ap.add_argument("--plan", action="store_true",
                    help="匯出後順便把 rt_detr 編成 TensorRT 引擎（這台上線用的格式）")
    ap.add_argument("--plan-only", action="store_true",
                    help="只編 TensorRT 引擎，不重新匯出任何 ONNX")
    ap.add_argument("--force", action="store_true",
                    help="覆蓋已存在的檔案（預設跳過，避免誤刪唯一一份可用引擎）")
    args = ap.parse_args()

    print(f"model_repository：{_REPO_DIR}")
    print(f"目標版本目錄：{args.version}\n")

    ok = True
    if not args.plan_only:
        for name in (args.only or sorted(EXPORTERS)):
            ok = EXPORTERS[name](args.version, args.force) and ok
            print()

    if args.plan or args.plan_only:
        ok = build_rt_detr_plan(args.version, args.force) and ok
        print()

    if not ok:
        print("❌ 有步驟沒完成，見上面訊息")
        return 1

    print("✅ 全部完成。接著起 Triton：./ai/run_triton.sh")
    if not (args.plan or args.plan_only):
        print("⚠️  rt_detr 是 tensorrt_plan，只有 ONNX 起不來 —— 記得再跑一次帶 --plan")
    return 0


if __name__ == "__main__":
    sys.exit(main())

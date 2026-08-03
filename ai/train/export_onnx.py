#!/usr/bin/env python3
"""AcT 權重 (.pth) → Triton 用的 ONNX。

這支腳本補的是 repo 既有的缺口：`run_triton.sh` 與 `.gitignore` 都指向
`python ai/export_models.py`，但那支檔案在 HEAD 並不存在。

輸出規格必須符合 `ai/triton_repo/action_transformer/config.pbtxt`：
    input  名稱 "input"  dims [1, 30, 34] FP32
    output 名稱 "output" dims [1, 2]      FP32
`max_batch_size: 0` 表示 dims 就是完整 shape（batch 固定為 1），所以不設 dynamic axes。

⚠ 上版本一律開新的版本目錄，不要覆蓋 `1/`。
   舊版是回滾路徑，而且 *.onnx 不進版控，覆蓋掉就沒了。
   產出後還要改 config.pbtxt 的 version_policy 才會生效——
   不要靠「Triton 自動載最大版本號」隱式切版，那個坑 rt_detr 踩過一次，
   整台 server 起不來。詳見 ai/triton_repo/README.md 的事故記錄。

用法：
    ai/.venv/bin/python ai/train/export_onnx.py \\
        --weights ai/action_transformer_v2.pth \\
        --out ai/triton_repo/action_transformer/2/model.onnx
"""

import argparse
import inspect
import sys
from pathlib import Path

import numpy as np
import torch

_AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AI_DIR))

from local_pipeline_eval import WINDOW_SIZE, ActionTransformer  # noqa: E402

INPUT_NAME = "input"
OUTPUT_NAME = "output"
FEATURE_DIM = 34
# 與 config.pbtxt 對齊：max_batch_size 0，batch 維固定寫在 dims 裡
BATCH_SIZE = 1
OPSET = 17


def load_model(weights_path):
    """載入權重到與正式管線完全相同的架構。"""
    model = ActionTransformer(input_dim=FEATURE_DIM, seq_len=WINDOW_SIZE, num_classes=2)
    state = torch.load(weights_path, map_location="cpu")
    if hasattr(state, "state_dict"):
        state = state.state_dict()
    model.load_state_dict(state)
    model.eval()
    return model


def verify(model, onnx_path, tolerance):
    """比對 PyTorch 與 ONNX 的輸出。沒裝 onnxruntime 就跳過並提醒。

    這一步不是形式主義：訓練端與 serving 端算出不同結果，
    症狀是「離線評估很好、上線變差」，而且極難追。
    """
    try:
        import onnxruntime
    except ImportError:
        print("⚠️  沒裝 onnxruntime，跳過數值比對。")
        print("   強烈建議裝起來再驗一次：ai/.venv/bin/pip install onnxruntime")
        return True

    rng = np.random.default_rng(0)
    sample = rng.standard_normal((BATCH_SIZE, WINDOW_SIZE, FEATURE_DIM)).astype(np.float32)
    with torch.no_grad():
        torch_output = model(torch.from_numpy(sample)).numpy()

    session = onnxruntime.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    onnx_output = session.run([OUTPUT_NAME], {INPUT_NAME: sample})[0]

    max_diff = float(np.max(np.abs(torch_output - onnx_output)))
    print(f"🔍 PyTorch vs ONNX 最大絕對差：{max_diff:.2e}")
    if max_diff > tolerance:
        print(f"❌ 超過容許值 {tolerance:.0e}，不要拿去 serving", file=sys.stderr)
        return False
    print("✅ 數值一致")
    return True


def parse_args():
    parser = argparse.ArgumentParser(description="AcT 權重轉 ONNX")
    parser.add_argument("--weights", required=True, help="輸入 .pth")
    parser.add_argument("--out", required=True, help="輸出 model.onnx")
    parser.add_argument("--tolerance", type=float, default=1e-4)
    parser.add_argument("--overwrite", action="store_true", help="允許覆蓋已存在的 ONNX")
    return parser.parse_args()


def main():
    args = parse_args()
    weights_path = Path(args.weights).resolve()
    out_path = Path(args.out).resolve()

    if not weights_path.is_file():
        print(f"❌ 找不到權重：{weights_path}", file=sys.stderr)
        return 1
    if out_path.exists() and not args.overwrite:
        print(f"❌ {out_path} 已存在。要覆蓋請加 --overwrite；"
              f"但正確做法是開新的版本目錄", file=sys.stderr)
        return 1

    model = load_model(weights_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dummy = torch.zeros(BATCH_SIZE, WINDOW_SIZE, FEATURE_DIM, dtype=torch.float32)

    # dynamo=False 走傳統 TorchScript 匯出路徑。
    # torch 2.9 起 export 預設 dynamo=True，那條路徑要額外裝 onnxscript；
    # 這顆模型只有 71K 參數、結構單純，舊路徑就夠，少一個依賴少一個坑。
    export_kwargs = {}
    if "dynamo" in inspect.signature(torch.onnx.export).parameters:
        export_kwargs["dynamo"] = False
    torch.onnx.export(
        model, dummy, str(out_path),
        input_names=[INPUT_NAME], output_names=[OUTPUT_NAME],
        opset_version=OPSET, do_constant_folding=True, **export_kwargs,
    )
    size_kb = out_path.stat().st_size / 1024
    print(f"💾 {out_path}（{size_kb:.0f} KB）")

    if not verify(model, out_path, args.tolerance):
        return 1

    print("\n下一步：")
    print(f"  1. 確認檔案就位：{out_path}")
    print("  2. 改 ai/triton_repo/action_transformer/config.pbtxt 的 version_policy 指向新版本")
    print("  3. 重啟 Triton：ai/run_triton.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())

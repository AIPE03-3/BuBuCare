#!/usr/bin/env bash
# 產生一份「CPU 版」的 Triton model_repository，給 GPU vs CPU 效能對照用。
#
# 為什麼要另開一份 repo：instance_group 的 KIND_GPU / KIND_CPU 寫在 config.pbtxt 裡，
# 而 config.pbtxt 就住在 model repository 底下。同一份 repo 沒辦法同時給兩台 server
# 用不同的 kind，所以只能複製一份出來改。
#
# 三顆模型：
#   yolo_pose          onnxruntime_onnx  ← 與 GPU 側同一份權重
#   rt_detr_onnx       onnxruntime_onnx  ← ⚠ 不是 rt_detr！見下
#   action_transformer onnxruntime_onnx  ← 與 GPU 側同一份權重
#
# ⚠ 為什麼 CPU 側用 rt_detr_onnx 而不是 rt_detr：
#   GPU 側的 rt_detr 是 platform=tensorrt_plan，跑的是 Blackwell 專屬編出的 model.plan。
#   TensorRT 引擎**不可能**在 CPU 上執行，換 KIND_CPU 也沒用。所以 CPU 側改用同一顆模型
#   的 ONNX 版本（rt_detr_onnx，權重與 rt_detr/3 同一份 onnx）。
#   → 對照報告因此必須分兩張表：「同格式 ONNX vs ONNX」看純硬體差距，
#     「上線配置 TensorRT vs ONNX」看實際決策數字。細節見 ai/BENCHMARK_GPU_VS_CPU.md。
#
# 權重檔用 hardlink（同一顆磁碟，零額外空間；改 config 不會動到原檔）。
# 產出的 ai/triton_repo_cpu/ 已在 .gitignore，不進版控。
#
# 用法： ./ai/make_cpu_repo.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${SRC:-$SCRIPT_DIR/triton_repo}"
DST="${DST:-$SCRIPT_DIR/triton_repo_cpu}"
MODELS="${MODELS:-yolo_pose rt_detr_onnx action_transformer}"

[[ -d "$SRC" ]] || { echo "❌ 找不到來源 repo：$SRC" >&2; exit 1; }

echo "📦 產生 CPU model repository"
echo "   來源：$SRC"
echo "   目標：$DST"
rm -rf "$DST"

for m in $MODELS; do
  [[ -d "$SRC/$m" ]] || { echo "❌ 來源缺模型目錄：$SRC/$m" >&2; exit 1; }
  mkdir -p "$DST/$m"

  # config.pbtxt：整份複製後把 instance_group 的 KIND_GPU 換成 KIND_CPU
  sed 's/KIND_GPU/KIND_CPU/g' "$SRC/$m/config.pbtxt" > "$DST/$m/config.pbtxt"
  if grep -q "KIND_GPU" "$DST/$m/config.pbtxt"; then
    echo "❌ $m 的 config.pbtxt 仍殘留 KIND_GPU" >&2; exit 1
  fi

  # 權重檔：hardlink（失敗就退回複製，例如跨檔案系統）
  for vdir in "$SRC/$m"/[0-9]*; do
    [[ -d "$vdir" ]] || continue
    v="$(basename "$vdir")"
    mkdir -p "$DST/$m/$v"
    for f in "$vdir"/*; do
      [[ -f "$f" ]] || continue
      # .plan 是 GPU 專屬的 TensorRT 引擎，CPU repo 不需要也不能用
      [[ "$f" == *.plan ]] && continue
      ln "$f" "$DST/$m/$v/$(basename "$f")" 2>/dev/null \
        || cp "$f" "$DST/$m/$v/$(basename "$f")"
    done
  done
  echo "   ✓ $m"
done

echo
echo "✅ 完成。起 CPU 版 Triton："
echo "   TRITON_NAME=nh-triton-cpu TRITON_GPUS=none \\"
echo "   HTTP_PORT=8020 GRPC_PORT=8021 METRICS_PORT=8022 \\"
echo "   MODEL_REPO=$DST \\"
echo "   LOAD_MODELS=\"$MODELS\" $SCRIPT_DIR/run_triton.sh"

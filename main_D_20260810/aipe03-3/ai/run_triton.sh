#!/usr/bin/env bash
# 啟動 Triton Inference Server，載入 ai/triton_repo 底下的模型
# （yolo_pose + rt_detr + action_transformer 三顆）。
#
# 把原本手打的 `docker run --gpus all ...` 記錄成可重複執行的 script，方便交接。
# 所有可調參數都走環境變數，需要改埠 / 換鏡像 / 換 repo 路徑時不用改這支檔案：
#
#   TRITON_IMAGE   Triton 容器鏡像（預設 nvcr.io/nvidia/tritonserver:25.10-py3）
#   TRITON_NAME    容器名稱（預設 nh-triton，比照 docker-compose 的 nh- 前綴慣例）
#   HTTP_PORT      Triton HTTP 埠（預設 8000）⚠ 與後端 uvicorn 撞埠，兩個不要同時起；
#                  若要同時跑，設 HTTP_PORT=8010 並讓 client 走對應的 TRITON_*_URL
#   GRPC_PORT      Triton gRPC 埠（預設 8001）
#   METRICS_PORT   Triton metrics 埠（預設 8002）
#   MODEL_REPO     model_repository 路徑（預設 <此 script 所在的 ai/>/triton_repo）
#   MODEL_CONTROL_MODE  模型控制模式（預設 explicit）——決定「best.pt 重訓後能不能
#                  線上熱載回 Triton」。D 組 model_deployment_agent 靠 POST
#                  /v2/repository/models/<name>/load 觸發熱切，只有 explicit 認這個端點。
#                  · explicit（預設）：啟動時 --load-model 逐顆載入現有三顆；agent 事後主動
#                    POST /load 熱載新版本目錄（如 rt_detr/2/），可控、可驗切換時機。
#                  · poll：Triton 每 REPO_POLL_SECS 秒自掃 repo 自動撿新版本（agent 不必打
#                    /load；打了會回 400，agent 有相容分支）。切換時機不可控。
#                  · none：全部啟動時載入、之後不可增刪版本（舊行為，熱載端點回 503）。
#   REPO_POLL_SECS poll 模式的輪詢秒數（預設 5，僅 MODEL_CONTROL_MODE=poll 時生效）
#   TRITON_GPUS    傳給 docker 的 --gpus 值（預設 all）。設成 none / 空字串＝不帶 --gpus，
#                  整台 server 退回 CPU（給 GPU vs CPU 效能對照用，見 ai/BENCHMARK_GPU_VS_CPU.md）。
#                  ⚠ CPU 模式下 rt_detr 載不起來：它是 platform=tensorrt_plan，TensorRT
#                    引擎不可能在 CPU 上跑。CPU 側請用 LOAD_MODELS 換成 rt_detr_onnx。
#   TRITON_CPUS    傳給 docker 的 --cpuset-cpus（預設空＝不限制）。對照量測要固定核心數才可重現。
#   LOAD_MODELS    要載入/檢查的模型清單（空白分隔，預設 "yolo_pose rt_detr action_transformer"）
#
# 用法：
#   ./ai/run_triton.sh          # 起 server（前景 docker run -d，起完印出健康狀態）
#   ./ai/run_triton.sh stop     # 停掉並移除容器
#
#   # CPU 對照用的第二台（不同容器名與埠，兩台可並存但不要同時受測）：
#   TRITON_NAME=nh-triton-cpu TRITON_GPUS=none \
#   HTTP_PORT=8020 GRPC_PORT=8021 METRICS_PORT=8022 \
#   MODEL_REPO="$(pwd)/ai/triton_repo_cpu" \
#   LOAD_MODELS="yolo_pose rt_detr_onnx action_transformer" ./ai/run_triton.sh
#
# 前置：Docker 已裝、GPU 直通可用（容器內 nvidia-smi 看得到卡）、模型已就位
#       （若缺 ONNX 先跑 python ai/export_models.py）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TRITON_IMAGE="${TRITON_IMAGE:-nvcr.io/nvidia/tritonserver:25.10-py3}"
TRITON_NAME="${TRITON_NAME:-nh-triton}"
HTTP_PORT="${HTTP_PORT:-8010}"
GRPC_PORT="${GRPC_PORT:-8011}"
METRICS_PORT="${METRICS_PORT:-8002}"
TRITON_NETWORK="${TRITON_NETWORK:-aipe03-3_default}"
MODEL_REPO="${MODEL_REPO:-$SCRIPT_DIR/triton_repo}"
MODEL_CONTROL_MODE="${MODEL_CONTROL_MODE:-explicit}"
REPO_POLL_SECS="${REPO_POLL_SECS:-5}"
TRITON_GPUS="${TRITON_GPUS:-all}"
TRITON_CPUS="${TRITON_CPUS:-}"
LOAD_MODELS="${LOAD_MODELS:-yolo_pose_trt}"

if [[ "${1:-}" == "stop" ]]; then
  echo "🛑 停止並移除容器 $TRITON_NAME ..."
  docker rm -f "$TRITON_NAME" 2>/dev/null && echo "✅ 已移除" || echo "（容器不存在，略過）"
  exit 0
fi

if [[ ! -d "$MODEL_REPO" ]]; then
  echo "❌ 找不到 model_repository：$MODEL_REPO" >&2
  exit 1
fi
# 每個模型的 1/model.onnx 依 .gitignore 不進 repo，clone 後需先重建。
# pose / rt_detr 是必要模型，缺檔就 hard-fail；action_transformer 的權重可能還沒有
# （action_transformer.pth 需跟組員要），缺 ONNX 只警告、不阻擋 pose/detr 啟動。
missing=()
model_weight() {
  local model="$1"
  if grep -q 'platform:[[:space:]]*"tensorrt_plan"' "$MODEL_REPO/$model/config.pbtxt" 2>/dev/null; then
    echo "model.plan"
  else
    echo "model.onnx"
  fi
}
for m in $LOAD_MODELS; do
  [[ "$m" == "action_transformer" ]] && continue   # 可選，缺檔只警告（見下）
  weight="$(model_weight "$m")"
  [[ -f "$MODEL_REPO/$m/1/$weight" ]] || missing+=("$m/$weight")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "❌ 缺少模型檔：${missing[*]}（$MODEL_REPO/<model>/1/model.onnx）" >&2
  echo "   先執行：python ai/export_models.py" >&2
  exit 1
fi
if [[ " $LOAD_MODELS " == *" action_transformer "* ]] \
   && [[ ! -f "$MODEL_REPO/action_transformer/1/model.onnx" ]]; then
  echo "⚠️  action_transformer 缺 ONNX（$MODEL_REPO/action_transformer/1/model.onnx）——" >&2
  echo "    可能還沒有 action_transformer.pth。Triton 會照常起，AcT 該顆會載入失敗，" >&2
  echo "    inference_test.py 會退回模擬機制。要補齊：取得權重後跑 python ai/export_models.py" >&2
fi

# 若同名容器還在，先移除（避免 name 衝突）
docker rm -f "$TRITON_NAME" >/dev/null 2>&1 || true

# 依控制模式組 tritonserver 參數：
#   explicit → 啟動時逐顆 --load-model（沒帶就會 0 顆載入），事後靠 agent POST /load 熱載新版本
#   poll     → --repository-poll-secs，Triton 自掃 repo，不需 --load-model
#   none     → 全載、之後不可熱載（舊行為）
triton_args=(tritonserver --model-repository=/models)
case "$MODEL_CONTROL_MODE" in
  explicit)
    triton_args+=(--model-control-mode=explicit)
    for m in $LOAD_MODELS; do
      # 只載入實際有 ONNX 的顆（action_transformer 缺檔時略過，比照前面的可選邏輯）
      weight="$(model_weight "$m")"
      [[ -f "$MODEL_REPO/$m/1/$weight" ]] && triton_args+=(--load-model="$m")
    done
    ;;
  poll)
    triton_args+=(--model-control-mode=poll --repository-poll-secs="$REPO_POLL_SECS")
    ;;
  none)
    triton_args+=(--model-control-mode=none)
    ;;
  *)
    echo "❌ 未知 MODEL_CONTROL_MODE：${MODEL_CONTROL_MODE}（可用 explicit / poll / none）" >&2
    exit 1
    ;;
esac

# --gpus：預設 all；TRITON_GPUS=none/空 → 完全不帶，整台退回 CPU（效能對照用）
docker_args=(-d --rm --name "$TRITON_NAME" --network "$TRITON_NETWORK")
if [[ -n "$TRITON_GPUS" && "$TRITON_GPUS" != "none" ]]; then
  docker_args+=(--gpus "$TRITON_GPUS")
fi
[[ -n "$TRITON_CPUS" ]] && docker_args+=(--cpuset-cpus "$TRITON_CPUS")

echo "🚀 啟動 Triton（${TRITON_IMAGE}）"
echo "   HTTP=$HTTP_PORT gRPC=$GRPC_PORT metrics=$METRICS_PORT"
echo "   model_repository=$MODEL_REPO"
echo "   models=$LOAD_MODELS"
echo "   gpus=${TRITON_GPUS:-none}$([[ -n "$TRITON_CPUS" ]] && echo "  cpuset=$TRITON_CPUS")"
echo "   control_mode=$MODEL_CONTROL_MODE$([[ $MODEL_CONTROL_MODE == poll ]] && echo "（poll ${REPO_POLL_SECS}s）")"
docker run "${docker_args[@]}" \
  -v "$MODEL_REPO:/models" \
  -p "$HTTP_PORT:8000" -p "$GRPC_PORT:8001" -p "$METRICS_PORT:8002" \
  "$TRITON_IMAGE" \
  "${triton_args[@]}" >/dev/null

echo "⏳ 等待 Triton 就緒 ..."
for i in $(seq 1 30); do
  code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$HTTP_PORT/v2/health/ready" 2>/dev/null || true)"
  if [[ "$code" == "200" ]]; then
    echo "✅ Triton ready（HTTP ${HTTP_PORT}）"
    for m in $LOAD_MODELS; do
      mcode="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$HTTP_PORT/v2/models/$m/ready" 2>/dev/null || true)"
      [[ "$mcode" == "200" ]] && echo "   ✓ $m 已載入" || echo "   ✗ $m 未就緒（HTTP ${mcode}）"
    done
    echo
    echo "查看日誌： docker logs -f $TRITON_NAME"
    echo "停止服務： ./ai/run_triton.sh stop"
    exit 0
  fi
  sleep 2
done

echo "❌ 逾時仍未就緒，印出容器日誌：" >&2
docker logs "$TRITON_NAME" 2>&1 | tail -30 >&2
exit 1

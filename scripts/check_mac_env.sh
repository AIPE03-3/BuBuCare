#!/usr/bin/env bash
# macOS 本機環境自檢 —— 中斷之後用這支判斷「做到哪裡了」，不要靠記憶。
#
# 對照 MAC_SETUP_WBS.md 的 WBS 表：這裡每一行對應一個 T 編號，
# 看到第一個 ❌ 就從那項開始接手。
#
# 用法： bash scripts/check_mac_env.sh
#
# 路徑一律以本檔位置推算 repo 根目錄，不寫死家目錄（護欄會擋，換機器也不會炸）。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TRITON_HTTP_PORT="${TRITON_HTTP_PORT:-8010}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
OLLAMA_PORT="${OLLAMA_PORT:-11434}"

ok()   { printf '✅ %s\n' "$1"; }
bad()  { printf '❌ %s  → %s\n' "$1" "$2"; }
info() { printf 'ℹ️  %s\n' "$1"; }

section() { printf '\n── %s ────────────────────────\n' "$1"; }

# 讀 repo 根 .env 的單一鍵值。刻意用 grep 而非 source：.env 裡有含空白與引號的值，
# source 進來會被 shell 重新解析（甚至執行到反引號），只是要讀一個值不值得冒這險。
env_val() {
  [[ -f .env ]] || return 0
  grep -E "^${1}=" .env 2>/dev/null | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'
}

# ── P0 環境地基 ──────────────────────────────────────────────
section "P0 環境地基"

docker info >/dev/null 2>&1 \
  && ok "T0-1 docker daemon（$(docker version --format '{{.Server.Os}}/{{.Server.Arch}}' 2>/dev/null)）" \
  || bad "T0-1 docker daemon 沒起來" "開 Docker Desktop：open -a Docker"

[[ "$(git config core.hooksPath 2>/dev/null)" == ".githooks" ]] \
  && ok "T0-2 pre-commit 護欄已開" \
  || bad "T0-2 護欄 hooks 沒開" "git config core.hooksPath .githooks"

# ffmpeg / mediamtx 只有 P4 串流需要；找不到不算致命，故用 info 而非 bad。
# 這台沒有 Homebrew，兩者都不在 PATH 上：ffmpeg 走 imageio-ffmpeg 附的靜態版（.env 指路），
# mediamtx 走 docker image。所以三種來源都要認，只認 PATH 會誤判成沒裝。
ENV_FFMPEG="$(env_val DETECT_STREAM_FFMPEG)"
if command -v ffmpeg >/dev/null 2>&1; then
  ok "T0-3 ffmpeg（$(command -v ffmpeg)）"
elif [[ -n "${DETECT_STREAM_FFMPEG:-}" && -x "${DETECT_STREAM_FFMPEG}" ]]; then
  ok "T0-3 ffmpeg（環境變數 DETECT_STREAM_FFMPEG）"
elif [[ -n "$ENV_FFMPEG" && -x "$ENV_FFMPEG" ]]; then
  ok "T0-3 ffmpeg（.env 的 DETECT_STREAM_FFMPEG）"
else
  info "T0-3 沒有 ffmpeg —— 只有 P4 推流需要，P1/P2 不受影響（clip 編碼走 PyAV）"
fi

if command -v mediamtx >/dev/null 2>&1; then
  ok "T0-3 mediamtx（$(command -v mediamtx)）"
elif docker image inspect bluenviron/mediamtx:latest >/dev/null 2>&1; then
  ok "T0-3 mediamtx（docker image bluenviron/mediamtx:latest）"
else
  info "T0-3 沒有 mediamtx —— 只有 P4 需要（docker pull bluenviron/mediamtx）"
fi

ai/.venv/bin/python -c "import kafka, dotenv, boto3, av, tritonclient" >/dev/null 2>&1 \
  && ok "T0-4 ai/.venv 套件齊（kafka/dotenv/boto3/av/tritonclient）" \
  || bad "T0-4 ai/.venv 缺套件" "uv pip install --python ai/.venv/bin/python kafka-python-ng python-dotenv boto3 av 'tritonclient[all]' clearml"

.venv/bin/python -c "import ollama, kafka, langgraph" >/dev/null 2>&1 \
  && ok "T0-5 根 .venv 套件齊（ollama/kafka/langgraph）" \
  || bad "T0-5 根 .venv 缺套件" "uv pip install --python .venv/bin/python ollama"

# ── P1 Triton ────────────────────────────────────────────────
section "P1 Triton（CPU / ONNX）"

for m in yolo_pose rt_detr action_transformer; do
  [[ -f "ai/triton_repo/$m/1/model.onnx" ]] \
    && ok "T1-1 $m/1/model.onnx" \
    || bad "T1-1 缺 $m/1/model.onnx" "ai/.venv/bin/python ai/export_models.py（不要帶 --plan）"
done

[[ -f "ai/triton_repo/rt_detr_onnx/1/model.onnx" ]] \
  && ok "T1-2 rt_detr_onnx/1/model.onnx（Mac 專用的 ONNX 版 detr）" \
  || bad "T1-2 缺 rt_detr_onnx 權重" "ln ai/triton_repo/rt_detr/1/model.onnx ai/triton_repo/rt_detr_onnx/1/model.onnx"

if curl -sf -m 3 "http://127.0.0.1:${TRITON_HTTP_PORT}/v2/health/ready" >/dev/null 2>&1; then
  ok "T1-3 Triton server ready（HTTP ${TRITON_HTTP_PORT}）"
  for m in yolo_pose rt_detr_onnx action_transformer; do
    code="$(curl -s -o /dev/null -w '%{http_code}' -m 3 "http://127.0.0.1:${TRITON_HTTP_PORT}/v2/models/$m/ready" 2>/dev/null)"
    [[ "$code" == "200" ]] && ok "T1-3 模型 $m 已載入" || bad "T1-3 模型 $m 未就緒（HTTP $code）" "docker logs nh-triton | tail -30"
  done
else
  bad "T1-3 Triton 沒起來（HTTP ${TRITON_HTTP_PORT}）" \
      "TRITON_GPUS=none HTTP_PORT=${TRITON_HTTP_PORT} GRPC_PORT=8011 LOAD_MODELS=\"yolo_pose rt_detr_onnx action_transformer\" ./ai/run_triton.sh"
fi

# .env 的 detr URL 要指到 rt_detr_onnx，指到 rt_detr 在這台一定載不起來（tensorrt_plan）
if grep -qE '^TRITON_DETR_URL=.*rt_detr_onnx' .env 2>/dev/null; then
  ok "T1-4 .env 的 TRITON_DETR_URL 已指向 rt_detr_onnx"
else
  bad "T1-4 .env 的 TRITON_DETR_URL 沒指向 rt_detr_onnx" \
      "加一行 TRITON_DETR_URL=http://127.0.0.1:${TRITON_HTTP_PORT}/rt_detr_onnx"
fi

# ── P2 端到端主鏈 ────────────────────────────────────────────
section "P2 端到端主鏈"

for c in nh-kafka nh-backend nh-frontend; do
  state="$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo "無")"
  [[ "$state" == "running" ]] && ok "T2-1 容器 $c running" || bad "T2-1 容器 $c 狀態=$state" "docker compose up -d"
done

code="$(curl -s -o /dev/null -w '%{http_code}' -m 5 "http://127.0.0.1:${BACKEND_PORT}/docs" 2>/dev/null)"
[[ "$code" == "200" ]] && ok "T2-1 backend /docs 200" || bad "T2-1 backend 打不到（HTTP $code）" "docker logs nh-backend | tail -30"

# ── P3 VLM ───────────────────────────────────────────────────
section "P3 VLM 二審"

if curl -sf -m 3 "http://127.0.0.1:${OLLAMA_PORT}/api/version" >/dev/null 2>&1; then
  ok "T3 ollama 服務活著"
  want="${VLM_MODEL_NAME:-qwen2.5vl:7b}"
  if ollama list 2>/dev/null | awk 'NR>1{print $1}' | grep -qx "$want"; then
    ok "T3-1 VLM 模型 $want 已下載"
  else
    bad "T3-1 找不到 VLM 模型 $want" "ollama pull $want（本機現有：$(ollama list 2>/dev/null | awk 'NR>1{printf "%s ", $1}'))"
  fi
else
  bad "T3 ollama 服務沒回應" "開 Ollama.app 或跑 ollama serve"
fi

# ── P4 串流 ──────────────────────────────────────────────────
section "P4 串流（MediaMTX）"

[[ -f streaming/mediamtx.yml ]] \
  && ok "T4-1 streaming/mediamtx.yml 已建立（含帳密，不進版控）" \
  || info "T4-1 還沒有 streaming/mediamtx.yml → cp streaming/mediamtx.yml.example streaming/mediamtx.yml"

if curl -sf -m 3 "http://127.0.0.1:9997/v3/paths/list" >/dev/null 2>&1; then
  ok "T4-2 MediaMTX API 活著（9997）"
  # ready:true 才代表真的有畫面進來。不要拿 WHEP 的狀態碼判斷 —— 頻道沒人推流時
  # WHEP 一樣回 2xx，會把空頻道全部誤判成有畫面。
  curl -s -m 3 "http://127.0.0.1:9997/v3/paths/list" \
    | python3 -c 'import json,sys
d=json.load(sys.stdin)
for p in d.get("items", []):
    print(("✅ T4-3 頻道 " if p.get("ready") else "ℹ️  T4-3 頻道 ") + p["name"] + ("（ready）" if p.get("ready") else "（等人推流）"))' 2>/dev/null
else
  info "T4-2 MediaMTX 沒起來 —— P1~P3 不受影響，做到 P4 再起"
fi

ENV_MEDIAMTX="$(env_val MEDIAMTX_BASE_URL)"
[[ -n "$ENV_MEDIAMTX" ]] \
  && ok "T4-2 .env 的 MEDIAMTX_BASE_URL=${ENV_MEDIAMTX}" \
  || info "T4-2 .env 還沒設 MEDIAMTX_BASE_URL（後端組不出 WHEP 網址，前端畫面會是空的）"

# ── 護欄（每階段結束都要綠燈）────────────────────────────────
section "護欄"
if python3 scripts/check_guardrails.py >/dev/null 2>&1; then
  ok "T0-7 check_guardrails 綠燈"
else
  bad "T0-7 護欄紅燈" "python3 scripts/check_guardrails.py 看詳細"
fi

printf '\n完整任務表與續接方式見 MAC_SETUP_WBS.md\n'

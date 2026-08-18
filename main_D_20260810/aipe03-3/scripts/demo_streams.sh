#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${DEMO_STREAM_STATE_DIR:-/tmp/nh-demo-streams}"
CHANNELS=(301 302 303 304)

# Each camera can use a different source. Environment variables allow callers
# to override the defaults without editing this script.
declare -A VIDEOS=(
  [301]="${DEMO_VIDEO_301:-${DEMO_VIDEO:-$ROOT_DIR/../input/test7.mp4}}"
  [302]="${DEMO_VIDEO_302:-$ROOT_DIR/../input/test8.mp4}"
  [303]="${DEMO_VIDEO_303:-$ROOT_DIR/../input/test5.mp4}"
  [304]="${DEMO_VIDEO_304:-$ROOT_DIR/../input/test6.mp4}"
)

stop_streams() {
  for id in "${CHANNELS[@]}"; do
    pidfile="$STATE_DIR/cam${id}.pid"
    if [[ -f "$pidfile" ]]; then
      pid="$(cat "$pidfile")"
      kill "$pid" 2>/dev/null || true
      pkill -P "$pid" 2>/dev/null || true
      rm -f "$pidfile"
    fi
  done
}

case "${1:-start}" in
  stop)
    stop_streams
    echo "示範推流已停止"
    ;;
  status)
    for id in "${CHANNELS[@]}"; do
      pidfile="$STATE_DIR/cam${id}.pid"
      if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        echo "cam${id}_ai running pid=$(cat "$pidfile")"
      else
        echo "cam${id}_ai stopped"
      fi
    done
    ;;
  logs)
    tail -n 80 "$STATE_DIR"/*.log
    ;;
  start)
    command -v ffmpeg >/dev/null || { echo "找不到 ffmpeg" >&2; exit 1; }
    for id in "${CHANNELS[@]}"; do
      [[ -f "${VIDEOS[$id]}" ]] || { echo "找不到 cam${id}_ai 影片：${VIDEOS[$id]}" >&2; exit 1; }
    done
    mkdir -p "$STATE_DIR"
    stop_streams

    for id in "${CHANNELS[@]}"; do
      log="$STATE_DIR/cam${id}.log"
      nohup bash -c '
        while true; do
          ffmpeg -nostdin -re -stream_loop -1 -i "$1" \
            -an -vf "scale=640:360,fps=10" \
            -c:v libx264 -preset ultrafast -tune zerolatency \
            -g 10 -keyint_min 10 -sc_threshold 0 \
            -f rtsp -rtsp_transport tcp "$2"
          echo "FFmpeg disconnected; retrying in 2 seconds" >&2
          sleep 2
        done
      ' _ "${VIDEOS[$id]}" "rtsp://127.0.0.1:8554/cam${id}_ai" >"$log" 2>&1 &
      echo $! >"$STATE_DIR/cam${id}.pid"
      echo "cam${id}_ai <- ${VIDEOS[$id]}"
    done
    echo "已啟動 cam301_ai～cam304_ai；斷線會自動重連"
    ;;
  *)
    echo "Usage: $0 [start|stop|status|logs]" >&2
    exit 2
    ;;
esac

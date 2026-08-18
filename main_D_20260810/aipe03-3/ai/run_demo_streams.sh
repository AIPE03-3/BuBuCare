#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUT_DIR="$SCRIPT_DIR/deepstream/input"
CACHE_DIR="$INPUT_DIR/.ai-cache"
RUNTIME_DIR="${TMPDIR:-/tmp}/aipe-demo-streams"
mkdir -p "$RUNTIME_DIR" "$CACHE_DIR"

FILES=(test.MOV test2.MOV test3.MOV test4.MOV)

stop_streams() {
  for id in 301 302 303 304; do
    for suffix in "" _ai; do
      pid_file="$RUNTIME_DIR/cam${id}${suffix}.pid"
      if [[ -f "$pid_file" ]]; then
        pid="$(cat "$pid_file")"
        kill "$pid" 2>/dev/null || true
        rm -f "$pid_file"
      fi
    done
  done
}

case "${1:-start}" in
  stop)
    stop_streams
    echo "Four demo publishers stopped"
    exit 0
    ;;
  status)
    for id in 301 302 303 304; do
      ai_pid_file="$RUNTIME_DIR/cam${id}_ai.pid"
      if [[ -f "$ai_pid_file" ]] && kill -0 "$(cat "$ai_pid_file")" 2>/dev/null; then
        echo "cam${id}_ai: running (PID $(cat "$ai_pid_file"))"
      else
        echo "cam${id}: stopped"
      fi
    done
    exit 0
    ;;
  start) ;;
  *) echo "Usage: $0 [start|stop|status]" >&2; exit 2 ;;
esac

stop_streams

for index in 0 1 2 3; do
  id=$((301 + index))
  input="$INPUT_DIR/${FILES[$index]}"
  cached="$CACHE_DIR/cam${id}_ai.mp4"
  [[ -f "$input" ]] || { echo "Missing video: $input" >&2; exit 1; }

  # Transcode once, then loop with stream copy. Continuous decoding/scaling of
  # four 1080p MOV files consumed about 160% CPU even though output was 10 FPS.
  if [[ ! -s "$cached" || "$input" -nt "$cached" ]]; then
    echo "Building low-resolution cache for cam${id} ..."
    ffmpeg -nostdin -hide_banner -loglevel warning -y -i "$input" \
      -map 0:v:0 -an -vf "fps=10,scale=640:360:flags=fast_bilinear,format=yuv420p" \
      -c:v h264_nvenc -preset p1 -tune ll -bf 0 -g 10 \
      -b:v 1M -maxrate 1M -bufsize 1M -movflags +faststart "$cached"
  fi

  nohup ffmpeg -nostdin -hide_banner -loglevel warning \
    -re -stream_loop -1 -i "$cached" \
    -map 0:v:0 -an -c:v copy \
      -f rtsp -rtsp_transport tcp "rtsp://127.0.0.1:8554/cam${id}_ai" \
    >"$RUNTIME_DIR/cam${id}_ai.log" 2>&1 &
  echo $! >"$RUNTIME_DIR/cam${id}_ai.pid"
done

echo "Four demo publishers started: cam301..cam304"
echo "Logs: $RUNTIME_DIR/cam<id>.log"

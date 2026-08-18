#!/usr/bin/env bash
set -euo pipefail

DEVICE_ID="${DEVICE_ID:-301}"
NAME="${DEEPSTREAM_NAME:-nh-deepstream-pose-${DEVICE_ID}}"
IMAGE="${DEEPSTREAM_IMAGE:-nvcr.io/nvidia/deepstream:9.1-triton-multiarch}"
NETWORK="${DEEPSTREAM_NETWORK:-aipe03-3_default}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEEPSTREAM_DIR="$SCRIPT_DIR/deepstream"
SOURCE_URI="${SOURCE_URI:-rtsp://nh-mediamtx:8554/cam${DEVICE_ID}_ai}"
CAMERA_ID="${CAMERA_ID:-Room_${DEVICE_ID}}"
SOURCE_WIDTH="${SOURCE_WIDTH:-640}"
SOURCE_HEIGHT="${SOURCE_HEIGHT:-360}"

case "${1:-start}" in
  stop)
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    echo "DeepStream pose stopped"
    exit 0
    ;;
  logs)
    exec docker logs -f "$NAME"
    ;;
  status)
    exec docker ps -a --filter "name=^/${NAME}$" --format 'table {{.Names}}\t{{.Status}}'
    ;;
  start) ;;
  *)
    echo "Usage: $0 [start|stop|status|logs]" >&2
    exit 2
    ;;
esac

if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
  echo "Docker network not found: $NETWORK (start docker compose first)" >&2
  exit 1
fi

if ! docker inspect nh-triton >/dev/null 2>&1; then
  echo "Triton is not running. Start it first with ./ai/run_triton.sh" >&2
  exit 1
fi

docker rm -f "$NAME" >/dev/null 2>&1 || true

docker run -d \
  --name "$NAME" \
  --restart unless-stopped \
  --gpus all \
  --network "$NETWORK" \
  -e DETECTION_UDP_HOST=host.docker.internal \
  -e DETECTION_UDP_PORT=19000 \
  -e DETECTION_DEVICE_ID="$DEVICE_ID" \
  -e DETECTION_CAMERA_ID="$CAMERA_ID" \
  -e DETECTION_EVERY_N=1 \
  -e DETECTION_SOURCE_WIDTH="$SOURCE_WIDTH" \
  -e DETECTION_SOURCE_HEIGHT="$SOURCE_HEIGHT" \
  -e SOURCE_URI="$SOURCE_URI" \
  -v "$DEEPSTREAM_DIR:/workspace/deepstream" \
  "$IMAGE" \
  bash /workspace/deepstream/run_pose_pipeline.sh >/dev/null

echo "DeepStream pose started: $NAME"
echo "Source: $SOURCE_URI (${SOURCE_WIDTH}x${SOURCE_HEIGHT})"
echo "Logs: $0 logs"

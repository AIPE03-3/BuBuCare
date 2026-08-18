#!/usr/bin/env bash
set -euo pipefail

NAME="${DEEPSTREAM_NAME:-nh-deepstream-pose-multi}"
IMAGE="${DEEPSTREAM_IMAGE:-nvcr.io/nvidia/deepstream:9.1-triton-multiarch}"
NETWORK="${DEEPSTREAM_NETWORK:-aipe03-3_default}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEEPSTREAM_DIR="$SCRIPT_DIR/deepstream"

case "${1:-start}" in
  stop)
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    echo "DeepStream four-source pose stopped"
    exit 0
    ;;
  logs)
    exec docker logs -f "$NAME"
    ;;
  status)
    exec docker ps -a --filter "name=^/${NAME}$" --format 'table {{.Names}}\t{{.Status}}'
    ;;
  start) ;;
  *) echo "Usage: $0 [start|stop|status|logs]" >&2; exit 2 ;;
esac

docker network inspect "$NETWORK" >/dev/null 2>&1 || {
  echo "Docker network not found: $NETWORK" >&2
  exit 1
}
docker inspect nh-triton >/dev/null 2>&1 || {
  echo "Triton is not running" >&2
  exit 1
}

# The four legacy workers must not continue feeding batch-1 requests while the
# batched worker is being measured.
for id in 301 302 303 304; do
  docker rm -f "nh-deepstream-pose-${id}" >/dev/null 2>&1 || true
done
docker rm -f "$NAME" >/dev/null 2>&1 || true

docker run -d \
  --name "$NAME" \
  --restart unless-stopped \
  --gpus all \
  --network "$NETWORK" \
  -e DETECTION_UDP_HOST=host.docker.internal \
  -e DETECTION_UDP_PORT=19000 \
  -e DETECTION_EVERY_N=1 \
  -e DETECTION_SOURCE_WIDTH=1920 \
  -e DETECTION_SOURCE_HEIGHT=1080 \
  -v "$DEEPSTREAM_DIR:/workspace/deepstream" \
  "$IMAGE" \
  bash /workspace/deepstream/run_pose_pipeline_multi.sh >/dev/null

echo "DeepStream four-source pose started: $NAME"
echo "Sources: cam301_ai, cam302_ai, cam303_ai, cam304_ai"
echo "Logs: $0 logs"

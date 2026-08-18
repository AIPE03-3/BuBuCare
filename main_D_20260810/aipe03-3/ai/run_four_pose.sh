#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACTION="${1:-start}"

for id in 301 302 303 304; do
  DEVICE_ID="$id" \
  DEEPSTREAM_NAME="nh-deepstream-pose-${id}" \
  SOURCE_URI="rtsp://nh-mediamtx:8554/cam${id}_ai" \
  SOURCE_WIDTH=640 \
  SOURCE_HEIGHT=360 \
  CAMERA_ID="Room_${id}" \
    "$SCRIPT_DIR/run_deepstream_pose.sh" "$ACTION"
done

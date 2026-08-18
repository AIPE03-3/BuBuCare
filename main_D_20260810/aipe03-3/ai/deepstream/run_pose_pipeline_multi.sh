#!/usr/bin/env bash
set -euo pipefail

# Keep at most one decoded frame per source. When inference falls behind, old
# frames are discarded so the browser receives current coordinates instead of
# a smooth but increasingly delayed replay.
while true; do
  gst-launch-1.0 -e \
    rtspsrc location=rtsp://host.docker.internal:8554/cam301_ai protocols=tcp latency=0 drop-on-latency=true ! \
      rtph264depay ! h264parse ! nvv4l2decoder ! \
      queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 ! mux.sink_0 \
    rtspsrc location=rtsp://host.docker.internal:8554/cam302_ai protocols=tcp latency=0 drop-on-latency=true ! \
      rtph264depay ! h264parse ! nvv4l2decoder ! \
      queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 ! mux.sink_1 \
    rtspsrc location=rtsp://host.docker.internal:8554/cam303_ai protocols=tcp latency=0 drop-on-latency=true ! \
      rtph264depay ! h264parse ! nvv4l2decoder ! \
      queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 ! mux.sink_2 \
    rtspsrc location=rtsp://host.docker.internal:8554/cam304_ai protocols=tcp latency=0 drop-on-latency=true ! \
      rtph264depay ! h264parse ! nvv4l2decoder ! \
      queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 ! mux.sink_3 \
    nvstreammux name=mux batch-size=4 width=1920 height=1080 live-source=true \
      sync-inputs=false batched-push-timeout=15000 ! \
    nvinferserver config-file-path=/workspace/deepstream/config/config_infer_yolo_pose.txt ! \
    fakesink sync=false
done

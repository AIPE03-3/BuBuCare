#!/usr/bin/env bash
set -euo pipefail

while true; do
  gst-launch-1.0 -e \
    rtspsrc location=rtsp://host.docker.internal:8554/cam301 \
      protocols=tcp latency=0 drop-on-latency=true ! \
      rtph264depay ! h264parse ! nvv4l2decoder ! \
      queue leaky=downstream max-size-buffers=1 ! mux.sink_0 \
    rtspsrc location=rtsp://host.docker.internal:8554/cam302 \
      protocols=tcp latency=0 drop-on-latency=true ! \
      rtph264depay ! h264parse ! nvv4l2decoder ! \
      queue leaky=downstream max-size-buffers=1 ! mux.sink_1 \
    rtspsrc location=rtsp://host.docker.internal:8554/cam303 \
      protocols=tcp latency=0 drop-on-latency=true ! \
      rtph264depay ! h264parse ! nvv4l2decoder ! \
      queue leaky=downstream max-size-buffers=1 ! mux.sink_2 \
    rtspsrc location=rtsp://host.docker.internal:8554/cam304 \
      protocols=tcp latency=0 drop-on-latency=true ! \
      rtph264depay ! h264parse ! nvv4l2decoder ! \
      queue leaky=downstream max-size-buffers=1 ! mux.sink_3 \
    nvstreammux name=mux \
      batch-size=4 \
      width=1920 \
      height=1080 \
      live-source=1 \
      sync-inputs=0 \
      batched-push-timeout=15000 ! \
    nvinferserver \
      config-file-path=/workspace/deepstream/config/config_infer_yolo_pose.txt ! \
    fakesink sync=false
done
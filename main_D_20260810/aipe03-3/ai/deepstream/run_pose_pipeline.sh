#!/usr/bin/env bash
set -euo pipefail

g++ -std=c++17 -O2 -rdynamic /workspace/deepstream/pose_pipeline.cpp \
  -o /tmp/aipe-pose-pipeline \
  -I/opt/nvidia/deepstream/deepstream/sources/includes \
  -L/opt/nvidia/deepstream/deepstream/lib \
  -Wl,-rpath,/opt/nvidia/deepstream/deepstream/lib \
  -lnvdsgst_meta -lnvds_meta \
  $(pkg-config --cflags --libs gstreamer-1.0)

while true; do
  /tmp/aipe-pose-pipeline
done

#!/usr/bin/env sh
# Container entrypoint.
#
# YOLO detection runs on onnxruntime against the ONNX model baked into the
# image (app/models/yolov8n.onnx) — torch / ultralytics are not installed.
# This just sanity-checks that runtime before launching FastAPI.

set -eu

if ! python -c 'import importlib.util, sys; sys.exit(0 if importlib.util.find_spec("onnxruntime") else 1)' 2>/dev/null; then
    echo "[entrypoint] WARNING: onnxruntime not installed; YOLO routes will return an error."
fi
if [ ! -f app/models/yolov8n.onnx ]; then
    echo "[entrypoint] WARNING: app/models/yolov8n.onnx missing; YOLO routes will return an error."
fi

exec fastapi run app/main.py --port 9090

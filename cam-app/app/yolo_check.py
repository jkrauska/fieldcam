"""YOLOv8 object detection via ONNX Runtime: count people and birds in an image.

Runtime is pure onnxruntime + numpy + Pillow — no torch / ultralytics. The model
ships as a pre-exported ONNX file (see app/models/yolov8n.onnx). Regenerate it with
the `export` extra (torch is local/dev only):
    uv run --extra export python -c \
        "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx', imgsz=640, opset=12)"
"""

import logging
import os
import socket
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

# COCO class IDs we care about
TARGET_CLASSES: dict[int, str] = {
    0: "person",
    14: "bird",
}

# COCO 80-class names, in model output order (replaces ultralytics' model.names).
COCO_NAMES: list[str] = [
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "airplane",
    "bus",
    "train",
    "truck",
    "boat",
    "traffic light",
    "fire hydrant",
    "stop sign",
    "parking meter",
    "bench",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
    "backpack",
    "umbrella",
    "handbag",
    "tie",
    "suitcase",
    "frisbee",
    "skis",
    "snowboard",
    "sports ball",
    "kite",
    "baseball bat",
    "baseball glove",
    "skateboard",
    "surfboard",
    "tennis racket",
    "bottle",
    "wine glass",
    "cup",
    "fork",
    "knife",
    "spoon",
    "bowl",
    "banana",
    "apple",
    "sandwich",
    "orange",
    "broccoli",
    "carrot",
    "hot dog",
    "pizza",
    "donut",
    "cake",
    "chair",
    "couch",
    "potted plant",
    "bed",
    "dining table",
    "toilet",
    "tv",
    "laptop",
    "mouse",
    "remote",
    "keyboard",
    "cell phone",
    "microwave",
    "oven",
    "toaster",
    "sink",
    "refrigerator",
    "book",
    "clock",
    "vase",
    "scissors",
    "teddy bear",
    "hair drier",
    "toothbrush",
]

DEFAULT_MODEL = "app/models/yolov8n.onnx"
IMG_SIZE = 640
# Match ultralytics predict() defaults so counts stay consistent with the old path.
NMS_IOU = 0.7

_session_cache: dict[str, Any] = {}


def _get_session(model_name: str):
    """Return a cached onnxruntime InferenceSession, loading from disk only once per path."""
    if model_name not in _session_cache:
        import onnxruntime as ort

        # Errors-only: silence the GPU device-discovery warnings emitted on
        # boards (e.g. Raspberry Pi) that expose a DRM node with no usable
        # inference GPU. We always run on CPU.
        ort.set_default_logger_severity(3)
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        _session_cache[model_name] = ort.InferenceSession(model_name, sess_options=opts, providers=["CPUExecutionProvider"])
    return _session_cache[model_name]


def _letterbox(img: Image.Image) -> np.ndarray:
    """Resize keeping aspect ratio, pad to IMG_SIZE square, return NCHW float32 [0,1] RGB."""
    w0, h0 = img.size
    r = min(IMG_SIZE / w0, IMG_SIZE / h0)
    nw, nh = round(w0 * r), round(h0 * r)
    resized = img.resize((nw, nh), Image.BILINEAR)
    canvas = Image.new("RGB", (IMG_SIZE, IMG_SIZE), (114, 114, 114))
    canvas.paste(resized, ((IMG_SIZE - nw) // 2, (IMG_SIZE - nh) // 2))
    arr = np.asarray(canvas, dtype=np.float32) / 255.0  # HWC
    return arr.transpose(2, 0, 1)[None]  # 1,3,H,W


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> list[int]:
    """Greedy NMS on xyxy boxes; returns kept indices."""
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        iou = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[1:][iou <= iou_thr]
    return keep


def _postprocess(output: np.ndarray, conf_threshold: float) -> list[tuple[int, float]]:
    """Decode YOLOv8 output [1,84,8400] -> list of (class_id, confidence) after per-class NMS."""
    preds = output[0].T  # [8400, 84]: cx,cy,w,h + 80 class scores
    cxcywh = preds[:, :4]
    class_scores = preds[:, 4:]
    cls_ids = class_scores.argmax(axis=1)
    confs = class_scores.max(axis=1)

    mask = confs >= conf_threshold
    if not mask.any():
        return []
    cxcywh, cls_ids, confs = cxcywh[mask], cls_ids[mask], confs[mask]

    # center xywh -> xyxy (letterboxed space is fine; we only count)
    xy = cxcywh[:, :2]
    wh = cxcywh[:, 2:]
    boxes = np.concatenate([xy - wh / 2, xy + wh / 2], axis=1)

    detections: list[tuple[int, float]] = []
    for cid in np.unique(cls_ids):
        idx = np.where(cls_ids == cid)[0]
        keep = _nms(boxes[idx], confs[idx], NMS_IOU)
        for k in keep:
            detections.append((int(cid), float(confs[idx][k])))
    return detections


def detect_objects(
    image_path: str | Path | None = None,
    *,
    model_name: str = DEFAULT_MODEL,
    conf_threshold: float = 0.25,
    detect_all: bool = False,
) -> dict[str, Any]:
    """
    Run YOLOv8 (ONNX) on an image and return counts of detected objects (people, birds).

    Returns:
        Dict with:
          - counts: dict[str, int]  e.g. {"person": 2, "bird": 5}
          - total: int
          - image_path: str
          - model: str
          - details: list[dict] per-detection class + confidence
          - error: str (only present on failure)
    """
    try:
        import onnxruntime  # noqa: F401
    except ImportError as e:
        install_hint = f"docker exec {socket.gethostname()} uv pip install onnxruntime --system"
        logging.warning("onnxruntime not installed: %s. Install with: %s", e, install_hint)
        return {
            "counts": None,
            "total": None,
            "image_path": str(image_path) if image_path else None,
            "model": model_name,
            "error": f"onnxruntime not installed. Install with: {install_hint}",
        }

    path = Path(image_path) if image_path else None
    if not path or not path.is_file():
        return {
            "counts": None,
            "total": None,
            "image_path": str(image_path) if image_path else None,
            "model": model_name,
            "error": f"Image file not found: {image_path}",
        }

    if not Path(model_name).is_file():
        return {
            "counts": None,
            "total": None,
            "image_path": str(path),
            "model": model_name,
            "error": f"Model file not found: {model_name}",
        }

    if not model_name.lower().endswith(".onnx"):
        # Most common cause: a stale YOLO_MODEL pointing at a torch .pt checkpoint.
        return {
            "counts": None,
            "total": None,
            "image_path": str(path),
            "model": model_name,
            "error": (
                f"Expected an ONNX model but got '{model_name}'. "
                f"Set YOLO_MODEL to an .onnx file (default: {DEFAULT_MODEL})."
            ),
        }

    try:
        session = _get_session(model_name)
        cpu_before = time.process_time()
        wall_before = time.monotonic()
        load_before = os.getloadavg()

        with Image.open(path) as im:
            tensor = _letterbox(im.convert("RGB"))
        output = session.run(None, {session.get_inputs()[0].name: tensor})[0]
        detections = _postprocess(output, conf_threshold)

        cpu_after = time.process_time()
        wall_after = time.monotonic()
        load_after = os.getloadavg()
    except Exception as e:
        logging.exception("ONNX inference failed")
        return {
            "counts": None,
            "total": None,
            "image_path": str(path),
            "model": model_name,
            "error": str(e),
        }

    counts: dict[str, int] = {} if detect_all else dict.fromkeys(TARGET_CLASSES.values(), 0)
    details: list[dict[str, Any]] = []

    for cls_id, conf in detections:
        if detect_all:
            name = COCO_NAMES[cls_id] if cls_id < len(COCO_NAMES) else f"class_{cls_id}"
        else:
            name = TARGET_CLASSES.get(cls_id)
            if not name:
                continue
        counts[name] = counts.get(name, 0) + 1
        details.append({"class": name, "confidence": round(conf, 3)})

    wall_secs = wall_after - wall_before
    cpu_secs = cpu_after - cpu_before

    return {
        "counts": counts,
        "total": sum(counts.values()),
        "image_path": str(path),
        "model": model_name,
        "details": details,
        "perf": {
            "wall_secs": round(wall_secs, 3),
            "cpu_secs": round(cpu_secs, 3),
            "cpu_pct": round(cpu_secs / wall_secs * 100, 1) if wall_secs > 0 else 0,
            "load_before": [round(x, 2) for x in load_before],
            "load_after": [round(x, 2) for x in load_after],
        },
    }


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]

    # Extract --model value
    model = DEFAULT_MODEL
    if "--model" in args:
        idx = args.index("--model")
        if idx + 1 < len(args):
            model = args[idx + 1]
            args = args[:idx] + args[idx + 2 :]
        else:
            print("--model requires a value", file=sys.stderr)
            sys.exit(1)

    flags = {a for a in args if a.startswith("-")}
    positional = [a for a in args if not a.startswith("-")]

    path = positional[0] if positional else None
    if path is None:
        try:
            from .config import settings

            path = settings.field_image_path
        except Exception:
            print("Usage: python -m app.yolo_check [image_path] [-v] [--all] [--model app/models/yolov8n.onnx]", file=sys.stderr)
            sys.exit(1)

    result = detect_objects(path, model_name=model, detect_all="--all" in flags)
    if result.get("error"):
        print(result["error"], file=sys.stderr)
        sys.exit(2)
    if "-v" in flags:
        import json

        print(json.dumps(result, indent=2))
    else:
        for name, n in sorted(result["counts"].items(), key=lambda x: -x[1]):
            print(f"{name}: {n}")

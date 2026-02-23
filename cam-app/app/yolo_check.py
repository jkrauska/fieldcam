"""YOLO-based object detection: count people and birds in an image."""

import logging
import os
import time
from pathlib import Path
from typing import Any

# COCO class IDs we care about
TARGET_CLASSES: dict[int, str] = {
    0: "person",
    14: "bird",
}

DEFAULT_MODEL = "yolov8n.pt"


def detect_objects(
    image_path: str | Path | None = None,
    *,
    model_name: str = DEFAULT_MODEL,
    conf_threshold: float = 0.25,
    detect_all: bool = False,
) -> dict[str, Any]:
    """
    Run YOLO on an image and return counts of detected objects (people, birds).

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
        from ultralytics import YOLO
    except ImportError as e:
        logging.warning("ultralytics not installed: %s", e)
        return {
            "counts": None,
            "total": None,
            "image_path": str(image_path) if image_path else None,
            "model": model_name,
            "error": "ultralytics not installed. Install with: uv add ultralytics",
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

    try:
        model = YOLO(model_name)
        cpu_before = time.process_time()
        wall_before = time.monotonic()
        load_before = os.getloadavg()
        predict_kwargs: dict[str, Any] = dict(
            source=str(path),
            conf=conf_threshold,
            verbose=False,
        )
        if not detect_all:
            predict_kwargs["classes"] = list(TARGET_CLASSES.keys())
        results = model.predict(**predict_kwargs)
        cpu_after = time.process_time()
        wall_after = time.monotonic()
        load_after = os.getloadavg()
    except Exception as e:
        logging.exception("YOLO inference failed")
        return {
            "counts": None,
            "total": None,
            "image_path": str(path),
            "model": model_name,
            "error": str(e),
        }

    counts: dict[str, int] = {} if detect_all else {name: 0 for name in TARGET_CLASSES.values()}
    details: list[dict[str, Any]] = []
    class_names = model.names  # COCO class name mapping from the model

    if results and results[0].boxes is not None and results[0].boxes.cls is not None:
        boxes = results[0].boxes
        classes = boxes.cls.int().tolist()
        confidences = (
            boxes.conf.float().tolist()
            if boxes.conf is not None
            else [0.0] * len(classes)
        )
        for cls_id, conf in zip(classes, confidences):
            if detect_all:
                name = class_names.get(cls_id, f"class_{cls_id}")
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
    flags = {a for a in args if a.startswith("-")}
    positional = [a for a in args if not a.startswith("-")]

    path = positional[0] if positional else None
    if path is None:
        try:
            from .config import settings
            path = settings.field_image_path
        except Exception:
            print("Usage: python -m app.yolo_check [image_path] [-v] [--all]", file=sys.stderr)
            sys.exit(1)

    result = detect_objects(path, detect_all="--all" in flags)
    if result.get("error"):
        print(result["error"], file=sys.stderr)
        sys.exit(2)
    if "-v" in flags:
        import json
        print(json.dumps(result, indent=2))
    else:
        for name, n in sorted(result["counts"].items(), key=lambda x: -x[1]):
            print(f"{name}: {n}")

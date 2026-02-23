"""YOLO-based object detection: count people and birds in an image."""

import logging
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
        results = model.predict(
            source=str(path),
            conf=conf_threshold,
            verbose=False,
            classes=list(TARGET_CLASSES.keys()),
        )
    except Exception as e:
        logging.exception("YOLO inference failed")
        return {
            "counts": None,
            "total": None,
            "image_path": str(path),
            "model": model_name,
            "error": str(e),
        }

    counts: dict[str, int] = {name: 0 for name in TARGET_CLASSES.values()}
    details: list[dict[str, Any]] = []

    if results and results[0].boxes is not None and results[0].boxes.cls is not None:
        boxes = results[0].boxes
        classes = boxes.cls.int().tolist()
        confidences = (
            boxes.conf.float().tolist()
            if boxes.conf is not None
            else [0.0] * len(classes)
        )
        for cls_id, conf in zip(classes, confidences):
            name = TARGET_CLASSES.get(cls_id)
            if name:
                counts[name] += 1
                details.append({"class": name, "confidence": round(conf, 3)})

    return {
        "counts": counts,
        "total": sum(counts.values()),
        "image_path": str(path),
        "model": model_name,
        "details": details,
    }


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else None
    if path is None:
        try:
            from .config import settings
            path = settings.field_image_path
        except Exception:
            print("Usage: python -m app.yolo_check [image_path]", file=sys.stderr)
            sys.exit(1)
    result = detect_objects(path)
    if result.get("error"):
        print(result["error"], file=sys.stderr)
        sys.exit(2)
    if len(sys.argv) > 2 and sys.argv[2] == "-v":
        import json
        print(json.dumps(result, indent=2))
    else:
        for name, n in result["counts"].items():
            print(f"{name}: {n}")

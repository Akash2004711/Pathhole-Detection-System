"""YOLO pothole detection service.

Loads the configured trained model exactly once per process and reuses it for
every request. Inference logic is kept separate from the API routes.

Honesty rule: if the model weights are missing or fail to load, this raises
ModelNotAvailable so the API returns a clear, actionable error - it NEVER
returns fabricated/mock detections.
"""
from __future__ import annotations

import base64
import io
import threading
import time
from pathlib import Path
from typing import Optional

from ..config import get_settings
from ..schemas import BoundingBox, Detection, DetectionResult
from . import file_utils


class ModelNotAvailable(RuntimeError):
    """Raised when valid YOLO weights cannot be located or loaded."""


class VideoProcessingError(RuntimeError):
    """Raised when a video cannot be decoded or processed."""


_lock = threading.Lock()
_model = None  # type: ignore[assignment]
_model_name: str = "unloaded"


def _load_model():
    """Lazily initialise and cache the Ultralytics YOLO model."""
    global _model, _model_name
    if _model is not None:
        return _model

    with _lock:
        if _model is not None:
            return _model

        s = get_settings()
        path = s.resolve_model_path()
        if not path.exists():
            raise ModelNotAvailable(
                f"YOLO model weights not found at '{path}'. "
                "Train or download a pothole model and set YOLO_MODEL_PATH "
                "in the backend .env file."
            )
        try:
            from ultralytics import YOLO  # imported lazily so tests can run without it
            _model = YOLO(str(path))
            _model_name = path.name
            return _model
        except ModelNotAvailable:
            raise
        except Exception as e:  # incompatible/corrupt weights
            raise ModelNotAvailable(
                f"Failed to load YOLO model from '{path}': {e}. "
                "Verify the weights are a valid Ultralytics .pt file "
                "compatible with the installed ultralytics version."
            ) from e


def model_is_ready() -> tuple[bool, str]:
    try:
        _load_model()
        return True, _model_name
    except ModelNotAvailable as e:
        return False, str(e)


def _pothole_keywords() -> list[str]:
    return get_settings().pothole_class_keywords


def _is_pothole(label: str, keywords: list[str]) -> bool:
    """True if the class name should be treated as a pothole.

    With no keywords configured every class is accepted; otherwise the label
    must contain one of the keywords (case-insensitive). This is what stops a
    generic COCO model from reporting cars/people as potholes.
    """
    if not keywords:
        return True
    low = (label or "").lower()
    return any(k in low for k in keywords)


def _extract_detections(results, frame: Optional[int] = None,
                        timestamp_ms: Optional[float] = None) -> list[Detection]:
    keywords = _pothole_keywords()
    out: list[Detection] = []
    for r in results:
        boxes = getattr(r, "boxes", None)
        if boxes is None:
            continue
        names = getattr(r, "names", {}) or {}
        for box in boxes:
            xyxy = box.xyxy[0].tolist()
            cls_id = int(box.cls[0])
            label = names.get(cls_id, str(cls_id))
            if not _is_pothole(label, keywords):
                continue  # ignore cars / cracks / any non-pothole class
            conf = round(float(box.conf[0]) * 100, 2)
            out.append(
                Detection(
                    class_name=label,
                    confidence=conf,
                    bbox=BoundingBox(x1=xyxy[0], y1=xyxy[1], x2=xyxy[2], y2=xyxy[3]),
                    frame=frame,
                    timestamp_ms=timestamp_ms,
                )
            )
    return out


def _cv_to_png_bytes(img):
    import cv2
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("Failed to encode annotated image.")
    return buf.tobytes()


def _draw_detections(img, detections: list[Detection]) -> str:
    """Render ONLY the pothole boxes onto a copy of the source image.

    Boxes are drawn here (rather than via ``result.plot()``) so the annotated
    image always matches the filtered pothole detections and never shows other
    classes such as cars.
    """
    import cv2
    canvas = img.copy()
    h, w = canvas.shape[:2]
    thickness = max(2, int(round(min(h, w) / 300)))
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = max(0.5, min(h, w) / 900)
    for d in detections:
        x1, y1, x2, y2 = int(d.bbox.x1), int(d.bbox.y1), int(d.bbox.x2), int(d.bbox.y2)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 0, 255), thickness)
        text = f"{d.class_name} {d.confidence:.0f}%"
        (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
        ty = y1 - 6 if (y1 - th - baseline - 6) > 0 else y1 + th + baseline + 4
        cv2.rectangle(canvas, (x1, ty - th - baseline), (x1 + tw + 4, ty + 4),
                      (0, 0, 255), cv2.FILLED)
        cv2.putText(canvas, text, (x1 + 2, ty - 2), font, scale, (255, 255, 255),
                    thickness, cv2.LINE_AA)
    png = _cv_to_png_bytes(canvas)
    b64 = base64.b64encode(png).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _decode_image_bytes(data: bytes):
    """Decode raw image bytes into an OpenCV BGR ndarray.

    Passing a numpy array to ``model.predict`` is stable across ultralytics
    versions (newer releases no longer accept a raw in-memory BytesIO source).
    """
    import cv2
    import numpy as np

    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise file_utils.InvalidFileError("Could not decode the image content.")
    return img


def detect_image(data: bytes, filename: str = "") -> DetectionResult:
    """Run pothole detection on a single image (bytes)."""
    s = get_settings()
    file_utils.validate_image(data, s.max_image_bytes, filename)
    model = _load_model()
    source = _decode_image_bytes(data)

    t0 = time.perf_counter()
    results = model.predict(
        source=source,
        conf=s.yolo_confidence_threshold,
        iou=s.yolo_iou_threshold,
        verbose=False,
    )
    elapsed = (time.perf_counter() - t0) * 1000

    detections = _extract_detections(results)
    max_conf = max((d.confidence for d in detections), default=None)
    annotated = _draw_detections(source, detections)

    return DetectionResult(
        success=True,
        model=_model_name,
        media_type="image",
        pothole_count=len(detections),
        max_confidence=max_conf,
        inference_time_ms=round(elapsed, 2),
        detections=detections,
        annotated_media=annotated,
    )


def detect_video(data: bytes, filename: str = "") -> DetectionResult:
    """Run genuine frame-sampled inference on an uploaded video."""
    import cv2
    import numpy as np  # noqa: F401  (ensures numpy available for cv2 ops)

    s = get_settings()
    file_utils.validate_video(data, s.max_video_bytes, filename)
    model = _load_model()

    tmp = file_utils.write_temp(data, file_utils.safe_extension(filename, file_utils.VIDEO_EXTS, ".mp4"))
    t0 = time.perf_counter()
    cap = cv2.VideoCapture(tmp)
    try:
        if not cap.isOpened():
            raise VideoProcessingError("Could not decode video. The file may be corrupted or use an unsupported codec.")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = total_frames / fps if fps else 0.0
        if s.max_video_duration_seconds and duration > s.max_video_duration_seconds:
            raise VideoProcessingError(
                f"Video duration ({duration:.1f}s) exceeds the limit of {s.max_video_duration_seconds}s."
            )

        stride = max(1, s.video_frame_sample_stride)
        all_detections: list[Detection] = []
        sampled = 0
        idx = -1
        best_frame = None
        best_dets: list[Detection] = []
        best_conf = -1.0

        while True:
            ok, frame = cap.read()
            if not ok:
                break
            idx += 1
            if idx % stride != 0:
                continue
            if sampled >= s.video_max_frames:
                break
            sampled += 1
            ts_ms = round((idx / fps) * 1000, 1)
            results = model.predict(
                source=frame,
                conf=s.yolo_confidence_threshold,
                iou=s.yolo_iou_threshold,
                verbose=False,
            )
            dets = _extract_detections(results, frame=idx, timestamp_ms=ts_ms)
            if dets:
                all_detections.extend(dets)
                frame_max = max(d.confidence for d in dets)
                if frame_max > best_conf:
                    best_conf = frame_max
                    best_frame = frame.copy()
                    best_dets = dets

        elapsed = (time.perf_counter() - t0) * 1000
        # Frame-level detections may repeat across adjacent frames; this count
        # is the number of per-frame detections, not unique physical potholes.
        max_conf = max((d.confidence for d in all_detections), default=None)
        annotated = _draw_detections(best_frame, best_dets) if best_frame is not None else None

        return DetectionResult(
            success=True,
            model=_model_name,
            media_type="video",
            pothole_count=len(all_detections),
            max_confidence=max_conf,
            inference_time_ms=round(elapsed, 2),
            detections=all_detections,
            annotated_media=annotated,
        )
    finally:
        cap.release()
        file_utils.remove_temp(tmp)

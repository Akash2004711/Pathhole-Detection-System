"""Detection endpoints (require an authenticated user).

Run real YOLO inference on uploaded images/videos. When Firebase Storage is
configured, the original media and the annotated result are uploaded and their
object paths returned so the client can attach them to a report submission.
"""
from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from .. import firebase_client
from ..auth import CurrentUser, get_current_user
from ..config import get_settings
from ..detection import file_utils, yolo_service
from ..detection.yolo_service import ModelNotAvailable, VideoProcessingError
from ..schemas import DetectionResult
from ..services import storage_service

router = APIRouter(prefix="/api/detection", tags=["detection"])

CONTENT_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                 "webp": "image/webp", "bmp": "image/bmp"}


async def _read_limited(file: UploadFile, max_bytes: int) -> bytes:
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {max_bytes // (1024 * 1024)} MB limit.",
        )
    return data


def _store_media(result: DetectionResult, user: CurrentUser, original: bytes,
                 original_name: str) -> tuple[str | None, str | None]:
    """Best-effort upload to Cloud Storage. Returns (original, annotated) paths."""
    if not firebase_client.is_available():
        return None, None
    try:
        bucket = firebase_client.bucket()
        prefix = f"detection_uploads/{user.uid}"
        ext = file_utils.safe_extension(original_name, file_utils.IMAGE_EXTS, ".jpg")
        orig_path = file_utils.generate_object_name(prefix, ext)
        storage_service.upload_bytes(orig_path, original,
                                     CONTENT_TYPES.get(ext.lstrip("."), "application/octet-stream"))
        ann_path = None
        if result.annotated_media and result.annotated_media.startswith("data:"):
            raw = base64.b64decode(result.annotated_media.split(",", 1)[1])
            ann_path = file_utils.generate_object_name(prefix, ".png")
            storage_service.upload_bytes(ann_path, raw, "image/png")
        # Don't ship the base64 blob to the client once stored.
        if ann_path:
            result.annotated_url = storage_service.signed_url(ann_path)
            result.annotated_media = None
        return orig_path, ann_path
    except Exception:
        # Storage failure must not break detection; return inline result.
        return None, None


@router.post("/image", response_model=DetectionResult)
async def detect_image(
    file: UploadFile = File(...),
    store: bool = Query(True, description="Upload media to Cloud Storage. "
                    "Set false for cheap, high-frequency live-camera frames."),
    user: CurrentUser = Depends(get_current_user),
):
    s = get_settings()
    data = await _read_limited(file, s.max_image_bytes)
    try:
        result = yolo_service.detect_image(data, file.filename or "")
    except ModelNotAvailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except file_utils.InvalidFileError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    if store:
        orig, ann = _store_media(result, user, data, file.filename or "")
        # Attach object references so the client can include them on submission.
        result.original_object = orig
        result.annotated_object = ann
    else:
        # Live-camera frame: the client draws its own overlay, so skip the
        # large base64 annotated image to keep each realtime frame light.
        result.annotated_media = None
    return result


@router.post("/video", response_model=DetectionResult)
async def detect_video(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
):
    s = get_settings()
    data = await _read_limited(file, s.max_video_bytes)
    try:
        return yolo_service.detect_video(data, file.filename or "")
    except ModelNotAvailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except VideoProcessingError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except file_utils.InvalidFileError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

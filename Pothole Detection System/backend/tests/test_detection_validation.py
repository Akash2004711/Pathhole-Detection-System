"""File-validation and detection-failure behaviour (no model weights needed)."""

import io

import pytest
from PIL import Image

from app.detection import file_utils
from app.detection.yolo_service import ModelNotAvailable, detect_image, model_is_ready


def _png_bytes(size=(20, 20)):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format="PNG")
    return buf.getvalue()


def test_validate_image_ok():
    data = _png_bytes()
    assert file_utils.validate_image(data, 1_000_000, "a.png") == data


def test_validate_image_rejects_garbage():
    with pytest.raises(file_utils.InvalidFileError):
        file_utils.validate_image(b"not-an-image", 1_000_000, "fake.png")


def test_validate_image_rejects_empty():
    with pytest.raises(file_utils.InvalidFileError):
        file_utils.validate_image(b"", 1_000_000, "empty.png")


def test_validate_image_rejects_too_large():
    with pytest.raises(file_utils.InvalidFileError):
        file_utils.validate_image(_png_bytes(), 10, "big.png")


def test_extension_sanitiser_blocks_traversal():
    assert file_utils.safe_extension("evil.png/../../etc/passwd", file_utils.IMAGE_EXTS, ".jpg") == ".jpg"
    assert file_utils.safe_extension("ok.png", file_utils.IMAGE_EXTS, ".jpg") == ".png"


def test_model_not_ready_honestly():
    ready, msg = model_is_ready()
    assert ready is False
    assert "model weights not found" in msg.lower()


def test_detect_image_raises_when_no_weights():
    # Must NOT fabricate results - it raises an actionable error instead.
    with pytest.raises(ModelNotAvailable):
        detect_image(_png_bytes(), "road.png")

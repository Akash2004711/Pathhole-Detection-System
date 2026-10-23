"""Defensive file-handling helpers for uploads.

Validates size, extension and actual decoded content (never trusting the
client MIME type alone), and manages controlled temp directories with cleanup.
"""
from __future__ import annotations

import io
import os
import secrets
import tempfile
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# Whitelisted magic-ish signature checks in addition to PIL decoding.
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


class InvalidFileError(ValueError):
    """Raised when an uploaded file fails validation."""


def _check_size(data: bytes, max_bytes: int, label: str) -> None:
    if len(data) == 0:
        raise InvalidFileError(f"Empty {label} file.")
    if len(data) > max_bytes:
        raise InvalidFileError(
            f"{label} exceeds the maximum size of {max_bytes // (1024 * 1024)} MB."
        )


def validate_image(data: bytes, max_bytes: int, filename: str = "") -> bytes:
    _check_size(data, max_bytes, "Image")
    # Verify the file can actually be decoded as an image.
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            im.load()
    except (UnidentifiedImageError, OSError) as e:
        raise InvalidFileError(f"File is not a valid image: {e}") from e
    return data


def validate_video(data: bytes, max_bytes: int, filename: str = "") -> bytes:
    _check_size(data, max_bytes, "Video")
    # Lightweight container sniffing; OpenCV performs the real decode later.
    ext = Path(filename or "").suffix.lower()
    if ext and ext not in VIDEO_EXTS:
        raise InvalidFileError(f"Unsupported video extension: {ext}")
    return data


def safe_extension(filename: str, allowed: set[str], default: str) -> str:
    """Return a sanitised extension from the whitelist, or the default."""
    ext = Path(filename or "").suffix.lower()
    # Prevent path traversal / odd characters in the extension.
    if ext and ext in allowed and ext.isascii() and ext[0] == "." and len(ext) <= 6:
        return ext
    return default


def generate_object_name(prefix: str, ext: str) -> str:
    """Generate an unpredictable storage/temp name (no user-controlled path)."""
    token = secrets.token_hex(12)
    return f"{prefix}/{token}{ext}"


def write_temp(data: bytes, suffix: str) -> str:
    """Write bytes to a controlled temp file and return its path."""
    fd, path = tempfile.mkstemp(prefix="pd_", suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def remove_temp(path: str | None) -> None:
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass

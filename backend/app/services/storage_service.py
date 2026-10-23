"""Cloud Storage media handling.

Uploads original/annotated/repair-evidence blobs under a controlled path
structure and returns short-lived signed read URLs so private report media is
not publicly accessible by default.
"""
from __future__ import annotations

import datetime as dt

from .. import firebase_client


def upload_bytes(object_path: str, data: bytes, content_type: str) -> str:
    """Upload bytes to a storage object and return the object name."""
    bucket = firebase_client.bucket()
    blob = bucket.blob(object_path)
    blob.upload_from_string(data, content_type=content_type)
    return object_path


def signed_url(object_path: str, expires_seconds: int = 3600) -> str | None:
    """Return a temporary signed read URL for a storage object (if present)."""
    if not object_path:
        return None
    try:
        bucket = firebase_client.bucket()
        blob = bucket.blob(object_path)
        if not blob.exists():
            return None
        expires = dt.timedelta(seconds=expires_seconds)
        return blob.generate_signed_url(expiration=expires)
    except Exception:
        # Never leak storage internals; a missing URL is a soft failure.
        return None


def report_object_path(report_id: str, kind: str, ext: str) -> str:
    """Canonical storage layout for report media."""
    assert kind in {"original", "annotated", "repair-evidence"}
    return f"reports/{report_id}/{kind}/{kind}{ext}"

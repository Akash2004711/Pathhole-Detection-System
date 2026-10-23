"""Firebase Admin SDK initialisation (lazy + safe).

The single Firebase app instance is created once and reused. If Firebase is
not configured (missing project id or service-account file), the accessors
raise a descriptive error so the API can return a clear 503 response rather
than pretending the database works.

Nothing here ever touches the frontend: privileged credentials stay server
side only.
"""
from __future__ import annotations

import threading
from typing import Any

import firebase_admin
from firebase_admin import credentials, firestore, storage
from firebase_admin import auth as _auth

from .config import get_settings

_lock = threading.Lock()
_app = None  # type: ignore[assignment]


class FirebaseNotConfigured(RuntimeError):
    """Raised when Firebase Admin SDK cannot be initialised."""


def _resolve_storage_bucket() -> str | None:
    s = get_settings()
    if s.firebase_storage_bucket:
        return s.firebase_storage_bucket
    if s.firebase_project_id:
        return f"{s.firebase_project_id}.appspot.com"
    return None


def get_app():
    """Return the initialised Firebase app, creating it on first use."""
    global _app
    if _app is not None:
        return _app

    with _lock:
        if _app is not None:
            return _app

        s = get_settings()
        cred_path = s.resolve_credentials_path()
        if not s.firebase_project_id or cred_path is None:
            raise FirebaseNotConfigured(
                "Firebase is not configured. Set FIREBASE_PROJECT_ID and "
                "FIREBASE_CREDENTIALS_PATH (service-account JSON) in the "
                "backend .env file."
            )

        cred = credentials.Certificate(str(cred_path))
        options: dict[str, Any] = {"projectId": s.firebase_project_id}
        bucket = _resolve_storage_bucket()
        if bucket:
            options["storageBucket"] = bucket

        # get_app() raises ValueError (not returns None) when the default app
        # does not exist, so probe it with try/except before initialising.
        try:
            _app = firebase_admin.get_app()
        except ValueError:
            _app = firebase_admin.initialize_app(cred, options, name="[DEFAULT]")
        return _app


def is_available() -> bool:
    """Non-throwing availability check used by the /health endpoint."""
    s = get_settings()
    try:
        get_app()
        return bool(s.firebase_project_id) and s.resolve_credentials_path() is not None
    except Exception:
        return False


def db() -> "firestore.Client":
    return firestore.client(app=get_app())


def bucket() -> "storage.Bucket":
    get_app()  # ensure initialised
    b = _resolve_storage_bucket()
    if not b:
        raise FirebaseNotConfigured("Firebase Storage bucket is not configured.")
    return storage.bucket(b, app=get_app())


def auth_verify_id_token(token: str) -> dict:
    """Verify a Firebase ID token, raising on invalid/expired tokens.

    Ensures the app is initialised first so an unconfigured environment
    surfaces as FirebaseNotConfigured (503) rather than a generic 401.
    """
    get_app()
    return _auth.verify_id_token(token, check_revoked=True)

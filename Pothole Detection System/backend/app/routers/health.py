"""Health + public runtime config endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from .. import firebase_client
from ..config import get_settings
from ..detection import yolo_service

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health():
    """Application health without exposing secrets."""
    model_ready, model_msg = yolo_service.model_is_ready()
    settings = get_settings()
    return {
        "status": "ok",
        "app_env": settings.app_env,
        "firebase_configured": firebase_client.is_available(),
        "model_ready": model_ready,
        "model_note": None if model_ready else model_msg,
        "maps_configured": settings.maps_enabled,
        "email_configured": settings.email_enabled,
    }


@router.get("/api/config")
def public_config():
    """Public, non-secret config the frontend needs at runtime.

    These values are safe to expose to the browser (Firebase web config and a
    referrer-restricted Maps key). Service-account and SMTP secrets never
    appear here.
    """
    s = get_settings()
    return {
        "apiKey": s.firebase_api_key,
        "authDomain": s.firebase_auth_domain,
        "projectId": s.firebase_project_id,
        "storageBucket": s.firebase_storage_bucket or (
            f"{s.firebase_project_id}.appspot.com" if s.firebase_project_id else ""
        ),
        "messagingSenderId": s.firebase_messaging_sender_id,
        "appId": s.firebase_app_id,
        "googleMapsApiKey": s.google_maps_api_key,
        "backendBaseUrl": s.app_base_url,
    }

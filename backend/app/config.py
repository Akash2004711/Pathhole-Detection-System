"""Application configuration loaded from environment variables / .env.

Uses pydantic-settings so every value is typed, validated and centrally
accessible. Nothing secret is hardcoded; all credentials come from the
environment (see backend/.env.example).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ directory (this file lives in backend/app/config.py)
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Application ----
    app_env: str = "development"
    app_base_url: str = "http://127.0.0.1:8000"
    frontend_origins: str = "http://localhost:5173,http://127.0.0.1:5500"

    # ---- AI / YOLO ----
    yolo_model_path: str = "models/pothole_yolov8.pt"
    yolo_confidence_threshold: float = 0.5
    yolo_iou_threshold: float = 0.45
    video_frame_sample_stride: int = 5
    video_max_frames: int = 600
    # Comma-separated class-name keywords treated as potholes. Any detection
    # whose class name does not contain one of these (case-insensitive) is
    # ignored, so a non-pothole model never reports cars as potholes.
    # Empty string means: accept every class the model returns.
    pothole_class_names: str = "pothole"

    @property
    def pothole_class_keywords(self) -> list[str]:
        return [k.strip().lower() for k in self.pothole_class_names.split(",") if k.strip()]

    # ---- Upload limits ----
    max_image_size_mb: int = 10
    max_video_size_mb: int = 100
    max_video_duration_seconds: int = 120

    # ---- Firebase ----
    firebase_project_id: str = ""
    firebase_credentials_path: str = ""
    google_application_credentials: str = ""
    firebase_storage_bucket: str = ""

    # ---- Registration ----
    # Shared secret required to self-register as a government_authority.
    # If empty, authority self-registration is disabled (users only).
    authority_signup_code: str = ""

    # Public web config (exposed to the frontend through /api/config)
    firebase_api_key: str = ""
    firebase_auth_domain: str = ""
    firebase_messaging_sender_id: str = ""
    firebase_app_id: str = ""
    google_maps_api_key: str = ""

    # ---- Email ----
    email_enabled: bool = False
    email_host: str = ""
    email_port: int = 587
    email_username: str = ""
    email_password: str = ""
    email_from: str = "no-reply@example.com"
    authority_alert_email: str = ""
    email_use_tls: bool = True

    @field_validator("yolo_confidence_threshold", "yolo_iou_threshold")
    @classmethod
    def _validate_0_1(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        return v

    # ---- Derived helpers ----
    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_origins.split(",") if o.strip()]

    def resolve_model_path(self) -> Path:
        """Return an absolute path for the YOLO weights."""
        p = Path(self.yolo_model_path)
        if not p.is_absolute():
            p = BACKEND_DIR / p
        return p

    def resolve_credentials_path(self) -> Path | None:
        """Locate the Firebase service-account JSON, if configured."""
        for raw in (self.firebase_credentials_path, self.google_application_credentials):
            if not raw:
                continue
            p = Path(raw)
            if not p.is_absolute():
                p = BACKEND_DIR / p
            if p.exists():
                return p
        return None

    @property
    def firebase_enabled(self) -> bool:
        return bool(self.firebase_project_id) and self.resolve_credentials_path() is not None

    @property
    def maps_enabled(self) -> bool:
        return bool(self.google_maps_api_key)

    @property
    def max_image_bytes(self) -> int:
        return self.max_image_size_mb * 1024 * 1024

    @property
    def max_video_bytes(self) -> int:
        return self.max_video_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""FastAPI application entry point.

Wires routers, CORS, unified error handling and serves the static frontend.
Run locally with:  uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import firebase_client
from .config import get_settings
from .firebase_client import FirebaseNotConfigured
from .routers import authority, detection, health, registration, reports

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pothole")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Log integration status once at startup (no fake success claims).
    from .detection import yolo_service
    ready, msg = yolo_service.model_is_ready()
    logger.info("Firebase configured: %s", firebase_client.is_available())
    logger.info("YOLO model ready: %s (%s)", ready, msg)
    yield


app = FastAPI(
    title="AI-Powered Pothole Detection and Reporting System",
    description=(
        "Computer-vision pothole detection (YOLO), Firebase authentication & "
        "Firestore reporting, GPS/Maps integration and authority workflow."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(FirebaseNotConfigured)
async def _firebase_handler(request: Request, exc: FirebaseNotConfigured):
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"success": False, "detail": str(exc)},
    )


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    # Log internally, never leak stack traces to clients.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"success": False, "detail": "Internal server error."},
    )


# ---- API routers ----
for r in (health.router, detection.router, reports.router, authority.router,
          registration.router):
    app.include_router(r)


# ---- Static frontend ----
# The frontend lives at ../Frontend. Mounted last so /api/* wins.
_frontend_dir = Path(__file__).resolve().parents[2] / "Frontend"
if _frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
else:  # pragma: no cover
    @app.get("/")
    def _root():
        return {"message": "Frontend directory not found.", "docs": "/docs"}

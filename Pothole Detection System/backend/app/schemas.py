"""Pydantic request/response schemas.

These define the public API contract and provide input validation for every
external request. Role is NEVER accepted from the client for privileged
operations - it is resolved from Firestore on the server.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

# ---- Enumerations (single source of truth) ----
ReportStatus = Literal[
    "submitted",       # initial
    "under_review",
    "verified",
    "rejected",
    "duplicate",
    "assigned",
    "in_progress",
    "resolved",
    "reopened",
]
Priority = Literal["low", "medium", "high", "critical"]
Role = Literal["user", "government_authority"]
MediaType = Literal["image", "video"]

# Which transitions are allowed from each state. Validated server-side.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "submitted": {"under_review", "verified", "rejected", "duplicate"},
    "under_review": {"verified", "rejected", "duplicate"},
    "verified": {"assigned", "rejected"},
    "assigned": {"in_progress", "verified"},
    "in_progress": {"resolved", "reopened"},
    "resolved": {"reopened"},
    "rejected": {"reopened"},
    "duplicate": {"reopened"},
    "reopened": {"under_review", "verified", "rejected", "duplicate"},
}


class BoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


class Detection(BaseModel):
    class_name: str
    confidence: float
    bbox: BoundingBox
    frame: Optional[int] = None
    timestamp_ms: Optional[float] = None


class DetectionResult(BaseModel):
    success: bool
    model: str
    media_type: MediaType
    pothole_count: int
    max_confidence: Optional[float] = None
    inference_time_ms: float
    detections: list[Detection] = Field(default_factory=list)
    annotated_url: Optional[str] = None
    annotated_media: Optional[str] = None  # base64 data URL for previews
    # Storage object references (populated when Cloud Storage is configured)
    original_object: Optional[str] = None
    annotated_object: Optional[str] = None


class GeoPoint(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class ReportCreate(BaseModel):
    media_type: MediaType = "image"
    pothole_count: int = Field(0, ge=0)
    detections: list[Detection] = Field(default_factory=list)
    max_confidence: Optional[float] = Field(None, ge=0, le=100)
    location: GeoPoint
    address: Optional[str] = Field(None, max_length=300)
    description: Optional[str] = Field(None, max_length=2000)
    category: Optional[str] = Field(None, max_length=80)
    original_object: Optional[str] = None
    annotated_object: Optional[str] = None


class ReportRead(BaseModel):
    id: str
    reporter_uid: str
    media_type: MediaType
    pothole_count: int
    max_confidence: Optional[float]
    status: ReportStatus
    priority: Optional[Priority]
    location: Optional[GeoPoint]
    address: Optional[str]
    description: Optional[str]
    category: Optional[str]
    original_url: Optional[str] = None
    annotated_url: Optional[str] = None
    assigned_team_id: Optional[str] = None
    assigned_team_name: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class VerifyRequest(BaseModel):
    decision: Literal["verified", "duplicate"]
    note: Optional[str] = Field(None, max_length=1000)


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000)


class PriorityRequest(BaseModel):
    priority: Priority
    reason: Optional[str] = Field(None, max_length=1000)


class AssignRequest(BaseModel):
    team_id: str
    target_date: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=1000)


class StatusUpdateRequest(BaseModel):
    status: ReportStatus
    note: Optional[str] = Field(None, max_length=1000)
    evidence_object: Optional[str] = None  # repair-evidence storage object


class MaintenanceTeamCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    contact_email: Optional[EmailStr] = None
    jurisdiction: Optional[str] = Field(None, max_length=120)
    active: bool = True

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class MaintenanceTeamUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    contact_email: Optional[EmailStr] = None
    jurisdiction: Optional[str] = Field(None, max_length=120)
    active: Optional[bool] = None


class MessageResponse(BaseModel):
    success: bool = True
    message: str


class RegisterProfileRequest(BaseModel):
    """Create the signed-in user's own Firestore profile at registration.

    The role defaults to a citizen. The government_authority role is only
    granted when the caller also supplies the shared AUTHORITY_SIGNUP_CODE,
    which is validated on the server (see routers/registration.py).
    """
    role: Role = "user"
    display_name: Optional[str] = Field(None, max_length=120)
    code: Optional[str] = Field(None, max_length=200)

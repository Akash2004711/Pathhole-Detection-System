"""Government authority endpoints - all require the government_authority role.

Role is verified server-side (see auth.require_authority). These endpoints
cover report management, verification, priority, assignment, repair tracking,
analytics and maintenance-team administration.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from .. import firebase_client
from ..auth import CurrentUser, require_authority
from ..config import get_settings
from ..schemas import (
    AssignRequest,
    MaintenanceTeamCreate,
    MaintenanceTeamUpdate,
    PriorityRequest,
    RejectRequest,
    StatusUpdateRequest,
    VerifyRequest,
)
from ..services import report_service
from ..services import storage_service
from ..detection import file_utils

router = APIRouter(prefix="/api/authority", tags=["authority"])


def _require_firebase():
    if not firebase_client.is_available():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable. Configure Firebase first.",
        )


@router.get("/reports")
def list_reports(
    rep_status: Optional[str] = Query(None, alias="status"),
    priority: Optional[str] = None,
    limit: int = Query(200, ge=1, le=500),
    user: CurrentUser = Depends(require_authority),
):
    _require_firebase()
    return {"reports": report_service.list_all_reports(
        {"status": rep_status, "priority": priority}, limit)}


@router.get("/analytics")
def analytics(user: CurrentUser = Depends(require_authority)):
    _require_firebase()
    return report_service.analytics()


@router.post("/reports/{report_id}/verify")
def verify(report_id: str, body: VerifyRequest, user: CurrentUser = Depends(require_authority)):
    _require_firebase()
    return report_service.verify_report(report_id, body.decision, body.note, user.uid, user.email)


@router.post("/reports/{report_id}/reject")
def reject(report_id: str, body: RejectRequest, user: CurrentUser = Depends(require_authority)):
    _require_firebase()
    return report_service.reject_report(report_id, body.reason, user.uid)


@router.patch("/reports/{report_id}/priority")
def priority(report_id: str, body: PriorityRequest, user: CurrentUser = Depends(require_authority)):
    _require_firebase()
    return report_service.set_priority(report_id, body.priority, body.reason, user.uid)


@router.post("/reports/{report_id}/assign")
def assign(report_id: str, body: AssignRequest, user: CurrentUser = Depends(require_authority)):
    _require_firebase()
    return report_service.assign_team(
        report_id, body.team_id, body.target_date, body.notes, user.uid)


@router.patch("/reports/{report_id}/status")
def update_status(report_id: str, body: StatusUpdateRequest,
                  user: CurrentUser = Depends(require_authority)):
    _require_firebase()
    return report_service.update_status(
        report_id, body.status, body.note, body.evidence_object, user.uid)


@router.post("/reports/{report_id}/evidence")
async def upload_evidence(
    report_id: str,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_authority),
):
    """Upload a repair-evidence photo (authority only). Returns the object path
    to include in a subsequent PATCH /status call marking the report resolved."""
    _require_firebase()
    s = get_settings()
    data = await file.read(s.max_image_bytes + 1)
    try:
        file_utils.validate_image(data, s.max_image_bytes, file.filename or "")
    except file_utils.InvalidFileError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))
    ext = file_utils.safe_extension(file.filename or "", file_utils.IMAGE_EXTS, ".jpg")
    path = storage_service.report_object_path(report_id, "repair-evidence", ext)
    storage_service.upload_bytes(path, data, "image/jpeg")
    return {"success": True, "evidence_object": path}


# ---- Maintenance teams ----

@router.get("/maintenance-teams")
def list_teams(user: CurrentUser = Depends(require_authority)):
    _require_firebase()
    return {"teams": report_service.list_teams()}


@router.post("/maintenance-teams")
def create_team(body: MaintenanceTeamCreate, user: CurrentUser = Depends(require_authority)):
    _require_firebase()
    team_id = report_service.create_team(body.model_dump(exclude_none=True))
    return {"id": team_id, "success": True}


@router.patch("/maintenance-teams/{team_id}")
def update_team(team_id: str, body: MaintenanceTeamUpdate,
                user: CurrentUser = Depends(require_authority)):
    _require_firebase()
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No fields to update.")
    return report_service.update_team(team_id, fields)

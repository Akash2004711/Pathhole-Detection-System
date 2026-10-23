"""User report endpoints (ownership enforced, role from server)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import firebase_client
from ..auth import CurrentUser, get_current_user
from ..firebase_client import FirebaseNotConfigured
from ..schemas import ReportCreate, ReportRead
from ..services import report_service

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _require_firebase():
    if not firebase_client.is_available():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable. Configure Firebase to submit or "
                   "read reports.",
        )


@router.post("", response_model=ReportRead)
def create_report(payload: ReportCreate, user: CurrentUser = Depends(get_current_user)):
    _require_firebase()
    try:
        report_id = report_service.create_report(payload, user.uid, user.email)
    except FirebaseNotConfigured as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    return report_service.get_report_for_user(report_id, user.uid, is_authority=False)


@router.get("/my")
def my_reports(user: CurrentUser = Depends(get_current_user)):
    _require_firebase()
    return {"reports": report_service.list_my_reports(user.uid)}


@router.get("/nearby")
def nearby(
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lng: Optional[float] = Query(None, ge=-180, le=180),
    radius_km: Optional[float] = Query(None, gt=0, le=200),
    user: CurrentUser = Depends(get_current_user),
):
    """Public map view: authorized-to-view reports with valid coordinates.

    No private reporter identity or contact details are returned.
    """
    _require_firebase()
    center = None
    if lat is not None and lng is not None:
        center = {"latitude": lat, "longitude": lng}
    return {"reports": report_service.list_nearby(radius_km, center)}


@router.get("/{report_id}", response_model=ReportRead)
def get_report(report_id: str, user: CurrentUser = Depends(get_current_user)):
    _require_firebase()
    is_auth = user.role == "government_authority"
    return report_service.get_report_for_user(report_id, user.uid, is_auth)


@router.get("/{report_id}/history")
def report_history(report_id: str, user: CurrentUser = Depends(get_current_user)):
    _require_firebase()
    # Ownership check first (raises 403/404 appropriately).
    is_auth = user.role == "government_authority"
    report_service.get_report_for_user(report_id, user.uid, is_auth)
    return {"history": report_service.get_history(report_id)}

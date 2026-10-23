"""Authorization tests: IDOR protection and role enforcement.

Uses the report service and auth dependency directly (no full HTTP override
for require_authority), so the real role checks run.
"""

import pytest
from fastapi import HTTPException

from app.auth import CurrentUser, require_authority
from app.services import report_service


def test_get_report_blocks_other_users(fake_db):
    rid = report_service.create_report(
        _payload(), "owner-uid", "owner@example.com")
    # A different user must not read someone else's private report.
    with pytest.raises(HTTPException) as exc:
        report_service.get_report_for_user(rid, "intruder-uid", is_authority=False)
    assert exc.value.status_code == 403
    # The owner may.
    r = report_service.get_report_for_user(rid, "owner-uid", is_authority=False)
    assert r["id"] == rid


def test_require_authority_blocks_non_authority():
    user = CurrentUser(uid="u", email="u@e.com", role="user", display_name="U")
    with pytest.raises(HTTPException) as exc:
        require_authority(user)
    assert exc.value.status_code == 403


def test_require_authority_allows_authority():
    off = CurrentUser(uid="a", email="a@e.com", role="government_authority", display_name="A")
    assert require_authority(off) is off


def _payload():
    from app.schemas import GeoPoint, ReportCreate
    return ReportCreate(
        media_type="image",
        pothole_count=1,
        detections=[],
        location=GeoPoint(latitude=1.0, longitude=2.0),
        address="Test Road",
    )

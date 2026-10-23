"""Registration profile endpoint.

The Firebase Auth account (email/password) is created by the browser, then this
endpoint creates the caller's own ``users/{uid}`` Firestore profile. Because it
writes through the Admin SDK, the profile does NOT depend on the client
Firestore security rules, so a missing/denied profile doc can no longer break
registration.

Role selection: a new account is a citizen by default. The
``government_authority`` role can be chosen at registration ONLY when the
caller also supplies the shared ``AUTHORITY_SIGNUP_CODE`` secret (validated
server-side). If the code is missing/incorrect, or authority self-registration
is disabled (empty code in .env), the request is rejected. The role is written
to BOTH Firestore (the app's source of truth) and the Auth custom claims (so
rules that inspect request.auth.token.role also pass).
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, status
from firebase_admin import auth as fauth

from .. import firebase_client
from ..auth import AUTHORITY_ROLE, USER_ROLE, CurrentUser, get_current_user
from ..config import get_settings
from ..schemas import RegisterProfileRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _utcnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@router.post("/register-profile")
def register_profile(
    req: RegisterProfileRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """Create/complete the signed-in user's own profile with the chosen role."""
    if not firebase_client.is_available():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase is not configured; registration is unavailable.",
        )

    settings = get_settings()
    requested_role = req.role if req.role in (USER_ROLE, AUTHORITY_ROLE) else USER_ROLE

    if requested_role == AUTHORITY_ROLE:
        if not settings.authority_signup_code:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Authority self-registration is disabled on this server.",
            )
        if (req.code or "") != settings.authority_signup_code:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="Invalid authority signup code.",
            )

    now = _utcnow()
    profile = {
        "uid": user.uid,
        "email": user.email,
        "display_name": (req.display_name or user.display_name or ""),
        "role": requested_role,
        "account_status": "active",
        "created_at": now,
        "updated_at": now,
    }
    firebase_client.db().collection("users").document(user.uid).set(profile, merge=True)

    # Mirror role into Auth custom claims (best-effort; Firestore is truth).
    try:
        fauth.set_custom_user_claims(user.uid, {"role": requested_role})
    except Exception:
        pass

    return {"success": True, "uid": user.uid, "role": requested_role}

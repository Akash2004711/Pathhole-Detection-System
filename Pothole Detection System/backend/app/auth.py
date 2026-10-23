"""Firebase ID-token authentication + role-based authorization.

Every protected endpoint depends on these helpers. The user's role is read
from Firestore (`users/{uid}.role`) - never trusted from the client. Custom
Firebase Auth claims are also honoured as a secondary signal.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import firebase_client
from .firebase_client import FirebaseNotConfigured

_bearer = HTTPBearer(auto_error=False)

USER_ROLE = "user"
AUTHORITY_ROLE = "government_authority"


@dataclass
class CurrentUser:
    uid: str
    email: str | None
    role: str
    display_name: str | None


def _credentials_optional_or_error(
    creds: HTTPAuthorizationCredentials | None,
) -> str:
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return creds.credentials


def _load_user(uid: str, decoded: dict) -> CurrentUser:
    """Resolve the authoritative role from Firestore, falling back to claims."""
    role = decoded.get("role")
    display_name = decoded.get("name")
    email = decoded.get("email")

    try:
        doc = firebase_client.db().collection("users").document(uid).get()
        if doc.exists:
            data = doc.to_dict() or {}
            # Firestore is the source of truth for roles.
            role = data.get("role", role)
            display_name = data.get("display_name", display_name)
            email = data.get("email", email)
    except FirebaseNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    return CurrentUser(
        uid=uid,
        email=email,
        role=role or USER_ROLE,
        display_name=display_name,
    )


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    token = _credentials_optional_or_error(creds)
    try:
        decoded = firebase_client.auth_verify_id_token(token)
    except FirebaseNotConfigured as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except Exception as e:
        # firebase_admin raises ValueError/ExpiredTokenError on bad tokens
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    uid = decoded.get("uid") or decoded.get("sub")
    if not uid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token missing uid.")
    return _load_user(uid, decoded)


def require_authority(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != AUTHORITY_ROLE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Government authority access required.",
        )
    return user

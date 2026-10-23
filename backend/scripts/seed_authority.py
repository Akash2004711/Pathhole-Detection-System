"""Create (or promote) a ready-to-use government authority login.

Idempotent seed helper for local demos and testing of the authority dashboard.
It uses the trusted Admin SDK (service-account), so it does NOT depend on the
client Firestore/Storage security rules being deployed.

For every run it:
  1. Finds the Firebase Auth user by email, or creates one with the given
     password if it does not exist yet.
  2. Writes the ``users/{uid}`` Firestore profile with role
     ``government_authority`` (the app's source of truth for roles).
  3. Mirrors the role into a custom Auth claim so rules that inspect
     ``request.auth.token.role`` also pass.

Usage (from the backend/ directory, with ENV_FILE unset so the real .env loads):
    python -m scripts.seed_authority
    python -m scripts.seed_authority official@example.com MyStrongPass
"""
from __future__ import annotations

import argparse
import sys
import time

# Ensure the backend package is importable when run as a script.
sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

from app import firebase_client  # noqa: E402

DEFAULT_EMAIL = "authority@example.com"
DEFAULT_PASSWORD = "Authority@2026"
DEFAULT_NAME = "Government Authority"
AUTHORITY_ROLE = "government_authority"


def _utcnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed a government authority login.")
    parser.add_argument("email", nargs="?", default=DEFAULT_EMAIL)
    parser.add_argument("password", nargs="?", default=DEFAULT_PASSWORD)
    parser.add_argument("--name", default=DEFAULT_NAME)
    args = parser.parse_args()

    if not firebase_client.is_available():
        print("Firebase is not configured. Set FIREBASE_PROJECT_ID and "
              "FIREBASE_CREDENTIALS_PATH in backend/.env first.")
        return 1

    from firebase_admin import auth

    # 1. Find or create the Auth account.
    try:
        user = auth.get_user_by_email(args.email)
        action = "existing"
    except Exception:
        user = auth.create_user(
            email=args.email, password=args.password, display_name=args.name)
        action = "created"

    # 2 + 3. Write the profile and mirror the role into custom claims.
    auth.set_custom_user_claims(user.uid, {"role": AUTHORITY_ROLE})
    now = _utcnow()
    profile = {
        "uid": user.uid,
        "email": args.email,
        "display_name": args.name,
        "role": AUTHORITY_ROLE,
        "account_status": "active",
        "updated_at": now,
    }
    firebase_client.db().collection("users").document(user.uid).set(profile, merge=True)

    print(f"Authority account {action}.")
    print(f"  email    : {args.email}")
    print(f"  password : {args.password}")
    print(f"  uid      : {user.uid}")
    print(f"  role     : {AUTHORITY_ROLE}")
    print("Sign in at http://127.0.0.1:8000/ to reach the authority dashboard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

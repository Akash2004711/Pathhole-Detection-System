"""Grant (or revoke) the government_authority role for a Firebase user.

Roles must be assigned by a trusted administrative process - never from the
client. Run this from a machine that has the service-account configured.

Usage:
    python -m scripts.grant_authority <email-or-uid> [--revoke]

It updates BOTH the Firestore users/{uid}.role (the app's source of truth) and
a custom Auth claim (so Storage/Firestore rules that inspect
request.auth.token.role also pass).
"""
from __future__ import annotations

import argparse
import sys

# Ensure the backend package is importable when run as a script.
sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

from app import firebase_client  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Grant/revoke government_authority role.")
    parser.add_argument("identifier", help="User email or UID")
    parser.add_argument("--revoke", action="store_true", help="Set role back to 'user'")
    args = parser.parse_args()

    if not firebase_client.is_available():
        print("Firebase is not configured. Set FIREBASE_PROJECT_ID and "
              "FIREBASE_CREDENTIALS_PATH in backend/.env first.")
        return 1

    from firebase_admin import auth
    try:
        if "@" in args.identifier:
            user = auth.get_user_by_email(args.identifier)
        else:
            user = auth.get_user(args.identifier)
    except Exception as e:
        print(f"Could not find user: {e}")
        return 1

    role = "user" if args.revoke else "government_authority"
    auth.set_custom_user_claims(user.uid, {"role": role})

    doc = firebase_client.db().collection("users").document(user.uid)
    doc.set({"role": role, "uid": user.uid}, merge=True)

    print(f"User {user.uid} role set to '{role}' in Auth claims and Firestore.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

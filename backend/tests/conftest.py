"""Shared pytest fixtures.

Firebase and the YOLO model are NOT required to run these tests: the
Firebase accessors and the model loader are monkeypatched with in-memory
fakes, and the auth dependency is overridden. Tests that need real model
weights are marked and skipped unless PDS_RUN_MODEL_TESTS=1.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

# Make `app` importable regardless of the working directory.
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("ENV_FILE", str(BACKEND_DIR / "tests" / "test.env"))
os.environ["FIREBASE_PROJECT_ID"] = ""
os.environ["FIREBASE_CREDENTIALS_PATH"] = ""


# ---------------- In-memory Firestore fake ----------------
class FakeDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data or {}
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data)


class FakeCollection:
    def __init__(self, store):
        self._store = store  # dict id -> data

    def document(self, doc_id=None):
        if doc_id is None:
            import uuid
            doc_id = uuid.uuid4().hex
        if doc_id not in self._store:
            self._store[doc_id] = None
        return FakeDocRef(self._store, doc_id)

    def doc(self, doc_id=None):
        return self.document(doc_id)

    def add(self, data):
        import uuid
        doc_id = uuid.uuid4().hex
        self._store[doc_id] = dict(data)
        return types.SimpleNamespace(id=doc_id)

    def where(self, *args):
        self._filter = args
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, n):
        return self

    def stream(self):
        items = []
        for k, v in self._store.items():
            if v is None:
                continue
            items.append(FakeDoc(k, v))
        return iter(items)


class FakeDocRef:
    def __init__(self, store, doc_id):
        self._store = store
        self.id = doc_id

    def get(self):
        data = self._store.get(self.id)
        return FakeDoc(self.id, data)

    def set(self, data, merge=False):
        if merge and self._store.get(self.id):
            self._store[self.id] = {**self._store[self.id], **data}
        else:
            self._store[self.id] = dict(data)
        return types.SimpleNamespace(id=self.id)

    def update(self, data):
        base = self._store.get(self.id) or {}
        self._store[self.id] = {**base, **data}


class FakeFirestore:
    def __init__(self):
        self._cols = {}

    def collection(self, name):
        self._cols.setdefault(name, {})
        return FakeCollection(self._cols[name])


@pytest.fixture
def fake_db(monkeypatch):
    from app import firebase_client

    db = FakeFirestore()
    monkeypatch.setattr(firebase_client, "db", lambda: db)
    monkeypatch.setattr(firebase_client, "is_available", lambda: True)
    # Storage signed URLs are disabled in tests.
    from app.services import storage_service
    monkeypatch.setattr(storage_service, "signed_url", lambda *a, **k: None)
    monkeypatch.setattr(storage_service, "upload_bytes", lambda *a, **k: "obj")
    return db


@pytest.fixture
def client(monkeypatch, fake_db):
    from fastapi.testclient import TestClient
    from app.main import app
    from app import auth

    # Override authentication with a fake signed-in user.
    fake_user = auth.CurrentUser(uid="test-user", email="test@example.com",
                                 role="user", display_name="Test User")

    def _override():
        return fake_user

    app.dependency_overrides[auth.get_current_user] = _override
    app.dependency_overrides[auth.require_authority] = lambda: auth.CurrentUser(
        uid="authority-user", email="gov@example.com",
        role="government_authority", display_name="Officer")

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def authority_client(client):
    return client

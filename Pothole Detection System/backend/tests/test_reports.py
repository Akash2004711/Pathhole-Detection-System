"""Report submission, ownership and validation tests (fake Firestore)."""

GOOD = {
    "media_type": "image",
    "pothole_count": 2,
    "max_confidence": 93.5,
    "detections": [
        {"class_name": "pothole", "confidence": 93.5,
         "bbox": {"x1": 1, "y1": 1, "x2": 10, "y2": 10}},
        {"class_name": "pothole", "confidence": 88.0,
         "bbox": {"x1": 20, "y1": 20, "x2": 40, "y2": 40}},
    ],
    "location": {"latitude": 12.97, "longitude": 77.59},
    "address": "MG Road",
    "description": "Deep pothole near bus stop",
}


def test_submit_report(client):
    r = client.post("/api/reports", json=GOOD)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "submitted"
    assert body["pothole_count"] == 2
    assert body["reporter_uid"] == "test-user"


def test_invalid_coordinates_rejected(client):
    bad = {**GOOD, "location": {"latitude": 200, "longitude": 0}}
    r = client.post("/api/reports", json=bad)
    assert r.status_code == 422  # Pydantic range validation


def test_my_reports_only_own(client):
    client.post("/api/reports", json=GOOD)
    r = client.get("/api/reports/my")
    assert r.status_code == 200
    reports = r.json()["reports"]
    assert all(x["reporter_uid"] == "test-user" for x in reports)


def test_history_created_on_submit(client):
    rid = client.post("/api/reports", json=GOOD).json()["id"]
    h = client.get(f"/api/reports/{rid}/history")
    assert h.status_code == 200
    events = [x["event"] for x in h.json()["history"]]
    assert "submitted" in events

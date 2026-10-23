"""Authority workflow: verification, priority, assignment, repair tracking,
status-transition validation and analytics. Uses the authority client (the
require_authority dependency is overridden to an authority user)."""

BASE = {
    "media_type": "image",
    "pothole_count": 1,
    "detections": [{"class_name": "pothole", "confidence": 90.0,
                    "bbox": {"x1": 0, "y1": 0, "x2": 5, "y2": 5}}],
    "location": {"latitude": 12.9, "longitude": 77.6},
    "address": "Ring Road",
}


def _make_report(client):
    return client.post("/api/reports", json=BASE).json()["id"]


def test_verify_report(client):
    rid = _make_report(client)
    r = client.post(f"/api/authority/reports/{rid}/verify", json={"decision": "verified"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "verified"


def test_invalid_transition_rejected(client):
    rid = _make_report(client)
    # submitted -> in_progress is not allowed.
    r = client.patch(f"/api/authority/reports/{rid}/status", json={"status": "in_progress"})
    assert r.status_code == 409


def test_resolve_requires_evidence(client):
    rid = _make_report(client)
    client.post(f"/api/authority/reports/{rid}/verify", json={"decision": "verified"})
    team = client.post("/api/authority/maintenance-teams", json={"name": "Team A"}).json()["id"]
    client.post(f"/api/authority/reports/{rid}/assign", json={"team_id": team})
    client.patch(f"/api/authority/reports/{rid}/status", json={"status": "in_progress"})
    # resolve without evidence -> 400
    r = client.patch(f"/api/authority/reports/{rid}/status", json={"status": "resolved"})
    assert r.status_code == 400
    # resolve with evidence -> 200
    r2 = client.patch(f"/api/authority/reports/{rid}/status",
                      json={"status": "resolved", "evidence_object": "reports/x/repair-evidence/e.jpg"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "resolved"


def test_priority_and_full_lifecycle(client):
    rid = _make_report(client)
    client.post(f"/api/authority/reports/{rid}/verify", json={"decision": "verified"})
    team = client.post("/api/authority/maintenance-teams",
                       json={"name": "Team B", "jurisdiction": "North"}).json()["id"]
    client.post(f"/api/authority/reports/{rid}/assign", json={"team_id": team})
    p = client.patch(f"/api/authority/reports/{rid}/priority", json={"priority": "critical"})
    assert p.status_code == 200

    hist = client.get(f"/api/reports/{rid}/history").json()["history"]
    events = [h["event"] for h in hist]
    assert "submitted" in events and "assigned" in events and "priority_changed" in events


def test_analytics(client):
    _make_report(client)
    r = client.get("/api/authority/analytics")
    assert r.status_code == 200
    body = r.json()
    assert body["total_reports"] >= 1
    assert "by_status" in body and "by_priority" in body

"""Health + config endpoints (no external credentials required)."""


def test_health_shape(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # Model is intentionally absent in the test env -> reported honestly.
    assert body["model_ready"] is False
    assert "not found" in (body["model_note"] or "").lower()


def test_config_has_no_secrets(client):
    body = client.get("/api/config").json()
    assert "googleMapsApiKey" in body
    # Service-account / SMTP secrets must never be exposed.
    for forbidden in ("email_password", "service_account", "private_key"):
        assert forbidden not in str(body).lower()

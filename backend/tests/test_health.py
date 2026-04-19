"""Tests for health check endpoints."""


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"


def test_health_detailed(client):
    resp = client.get("/health/detailed")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "obs_count" in data
    assert "models_loaded" in data
    assert isinstance(data["model_names"], list)

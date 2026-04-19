"""Tests for observations endpoint."""


def test_observations_stats(client):
    resp = client.get("/api/observations/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_observations_stats_fields(client):
    resp = client.get("/api/observations/stats")
    data = resp.json()
    if data:
        entry = data[0]
        assert "station_id" in entry
        assert "source" in entry
        assert "row_count" in entry
        assert "earliest" in entry
        assert "latest" in entry

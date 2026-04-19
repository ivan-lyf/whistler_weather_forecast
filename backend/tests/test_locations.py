"""Tests for locations endpoint."""


def test_locations_returns_list(client):
    resp = client.get("/api/locations")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_locations_have_required_fields(client):
    resp = client.get("/api/locations")
    data = resp.json()
    if len(data) > 0:
        loc = data[0]
        assert "name" in loc
        assert "elevation_m" in loc
        assert "latitude" in loc
        assert "longitude" in loc


def test_locations_three_elevations(client, seed_locations):
    resp = client.get("/api/locations")
    data = resp.json()
    names = {d["name"] for d in data}
    assert "base" in names
    assert "mid" in names
    assert "alpine" in names

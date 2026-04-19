"""Tests for forecast endpoints."""


def test_forecast_current(client):
    resp = client.get("/api/forecast/current")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data


def test_forecast_stats(client):
    resp = client.get("/api/forecast/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_forecast_stats_by_location(client):
    resp = client.get("/api/forecast/stats/by-location")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_predictions_default(client):
    resp = client.get("/api/predictions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_predictions_with_params(client):
    resp = client.get("/api/predictions", params={
        "start": "2025-11-25T00:00:00+00:00",
        "end": "2025-11-25T06:00:00+00:00",
        "location": "alpine",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for p in data:
        assert p["location"] == "alpine"


def test_predictions_with_location_filter(client):
    resp_alpine = client.get("/api/predictions", params={
        "start": "2025-11-25T00:00:00+00:00",
        "end": "2025-11-25T03:00:00+00:00",
        "location": "alpine",
    })
    resp_base = client.get("/api/predictions", params={
        "start": "2025-11-25T00:00:00+00:00",
        "end": "2025-11-25T03:00:00+00:00",
        "location": "base",
    })
    assert resp_alpine.status_code == 200
    assert resp_base.status_code == 200


def test_predictions_url_encoded_plus(client):
    """The + sign in timezone offset gets URL-decoded as space."""
    resp = client.get("/api/predictions?start=2025-11-25T00:00:00%2B00:00&end=2025-11-25T06:00:00%2B00:00")
    assert resp.status_code == 200


def test_predictions_invalid_location(client):
    """Invalid location should return 400."""
    resp = client.get("/api/predictions", params={
        "start": "2025-11-25T00:00:00+00:00",
        "end": "2025-11-25T06:00:00+00:00",
        "location": "summit",
    })
    assert resp.status_code == 400
    assert "Invalid location" in resp.json()["detail"]


def test_predictions_invalid_datetime(client):
    """Malformed datetime should return 400."""
    resp = client.get("/api/predictions", params={
        "start": "not-a-date",
        "end": "2025-11-25T06:00:00+00:00",
    })
    assert resp.status_code == 400
    assert "Invalid datetime" in resp.json()["detail"]


def test_predictions_end_before_start(client):
    """end < start should return 400."""
    resp = client.get("/api/predictions", params={
        "start": "2025-11-25T06:00:00+00:00",
        "end": "2025-11-25T00:00:00+00:00",
    })
    assert resp.status_code == 400
    assert "end must be after start" in resp.json()["detail"]


def test_predictions_range_too_large(client):
    """Range > 365 days should return 400."""
    resp = client.get("/api/predictions", params={
        "start": "2023-01-01T00:00:00+00:00",
        "end": "2025-01-01T00:00:00+00:00",
    })
    assert resp.status_code == 400
    assert "too large" in resp.json()["detail"]


def test_comparison_default(client):
    resp = client.get("/api/comparison")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        assert "raw_gfs_snowfall_cm" in data[0]
        assert "corrected_snowfall_cm" in data[0]
        assert "observed_snowfall_cm" in data[0]


def test_comparison_with_location(client):
    resp = client.get("/api/comparison", params={
        "start": "2025-11-25T00:00:00+00:00",
        "end": "2025-11-25T06:00:00+00:00",
        "location": "base",
    })
    assert resp.status_code == 200


def test_comparison_invalid_location(client):
    resp = client.get("/api/comparison", params={
        "start": "2025-11-25T00:00:00+00:00",
        "end": "2025-11-25T06:00:00+00:00",
        "location": "peak",
    })
    assert resp.status_code == 400


def test_metrics(client):
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


def test_performance(client):
    resp = client.get("/api/performance")
    assert resp.status_code == 200
    data = resp.json()
    assert "rolling_7d" in data
    assert "rolling_30d" in data
    assert "baselines" in data
    assert "drift_alerts" in data


def test_performance_trend(client):
    resp = client.get("/api/performance/trend", params={
        "target": "snowfall_24h",
        "location": "alpine",
        "days": 7,
    })
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_performance_trend_invalid_location(client):
    resp = client.get("/api/performance/trend", params={
        "target": "snowfall_24h",
        "location": "peak",
        "days": 7,
    })
    assert resp.status_code == 400


def test_predictions_latest(client):
    resp = client.get("/api/predictions/latest")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_predictions_latest_with_location(client):
    resp = client.get("/api/predictions/latest", params={"location": "alpine"})
    assert resp.status_code == 200


def test_predictions_latest_invalid_location(client):
    resp = client.get("/api/predictions/latest", params={"location": "summit"})
    assert resp.status_code == 400

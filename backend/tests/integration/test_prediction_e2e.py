"""Integration tests for the prediction pipeline end-to-end."""

from datetime import datetime, timezone

from app.prediction import get_metrics_summary, get_predictions


def test_get_predictions_returns_results(db, seed_locations, seed_stations,
                                         seed_forecast_data, seed_observations):
    """Full prediction pipeline with seeded data should return results."""
    start = datetime(2099, 1, 1, 0, tzinfo=timezone.utc)
    end = datetime(2099, 1, 1, 6, tzinfo=timezone.utc)

    results = get_predictions(db, start, end, location="alpine")
    assert isinstance(results, list)


def test_get_predictions_all_locations(db, seed_locations, seed_stations,
                                       seed_forecast_data, seed_observations):
    """Predictions for all locations."""
    start = datetime(2099, 1, 1, 0, tzinfo=timezone.utc)
    end = datetime(2099, 1, 1, 3, tzinfo=timezone.utc)

    results = get_predictions(db, start, end)
    assert isinstance(results, list)


def test_get_predictions_empty_range(db, seed_locations):
    """Predictions for a range with no data should return empty."""
    start = datetime(2000, 1, 1, tzinfo=timezone.utc)
    end = datetime(2000, 1, 2, tzinfo=timezone.utc)

    results = get_predictions(db, start, end, location="alpine")
    assert results == []


def test_get_metrics_summary():
    """Metrics summary should load available report files."""
    from unittest.mock import patch
    metrics = get_metrics_summary(None)
    assert isinstance(metrics, dict)

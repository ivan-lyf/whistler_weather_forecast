"""Integration tests for database operations."""

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import pytest

from app.models.location import Location
from app.models.station import Station
from app.models.observation import ObsHourly
from app.models.forecast import ForecastRun, ForecastValue
from app.models.training_label import TrainingLabel


def test_db_connection(db):
    result = db.execute(text("SELECT 1")).scalar()
    assert result == 1


def test_location_unique_name(db, seed_locations):
    """Duplicate location name should fail."""
    dup = Location(name="base", latitude=0, longitude=0, elevation_m=0)
    db.add(dup)
    with pytest.raises(IntegrityError):
        db.flush()


def test_obs_unique_constraint(db, seed_stations):
    """Duplicate (station_id, observed_at) should fail."""
    ts = datetime(2025, 6, 1, tzinfo=timezone.utc)
    db.add(ObsHourly(station_id=100, observed_at=ts, temperature_c=5.0))
    db.flush()

    db.add(ObsHourly(station_id=100, observed_at=ts, temperature_c=6.0))
    with pytest.raises(IntegrityError):
        db.flush()


def test_forecast_run_unique_constraint(db):
    """Duplicate (provider, model_name, run_at) should fail."""
    ts = datetime(2025, 6, 1, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    db.add(ForecastRun(provider="test", model_name="test", run_at=ts, fetched_at=now))
    db.flush()

    db.add(ForecastRun(provider="test", model_name="test", run_at=ts, fetched_at=now))
    with pytest.raises(IntegrityError):
        db.flush()


def test_training_label_unique_constraint(db, seed_locations):
    """Duplicate (location_id, target_time) should fail."""
    ts = datetime(2099, 6, 1, tzinfo=timezone.utc)
    db.add(TrainingLabel(location_id=1, target_time=ts, label_24h_snowfall_cm=5.0))
    db.flush()

    db.add(TrainingLabel(location_id=1, target_time=ts, label_24h_snowfall_cm=6.0))
    with pytest.raises(IntegrityError):
        db.flush()


def test_forecast_value_fk_constraint(db, seed_locations):
    """ForecastValue must reference valid forecast_run_id."""
    fv = ForecastValue(
        forecast_run_id=99999, location_id=1,
        valid_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        lead_hours=0,
    )
    db.add(fv)
    with pytest.raises(IntegrityError):
        db.flush()


def test_seed_and_query(db, seed_locations, seed_stations, seed_observations):
    """End-to-end: seed data and query it back."""
    count = db.execute(text(
        "SELECT COUNT(*) FROM obs_hourly WHERE station_id = 100"
    )).scalar()
    assert count > 0

    stations = db.execute(text(
        "SELECT COUNT(*) FROM stations WHERE source = 'open_meteo'"
    )).scalar()
    assert stations >= 2

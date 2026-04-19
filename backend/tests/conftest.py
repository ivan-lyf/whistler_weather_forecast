"""Shared test fixtures. Uses the real PostgreSQL database with transactions rolled back."""

import pickle
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.forecast import ForecastRun, ForecastValue
from app.models.location import Location
from app.models.observation import ObsHourly
from app.models.station import Station
from app.models.training_label import TrainingLabel

# Use the real database but roll back after each test
engine = create_engine(settings.database_url)
TestSession = sessionmaker(bind=engine)


@pytest.fixture()
def db():
    """Provide a transactional DB session that rolls back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestSession(bind=connection)

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db):
    """FastAPI test client with DB dependency overridden."""
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def seed_locations(db):
    """Seed 3 locations."""
    locations = [
        Location(id=1, name="base", latitude=50.1145, longitude=-122.954, elevation_m=675),
        Location(id=2, name="mid", latitude=50.107, longitude=-122.948, elevation_m=1500),
        Location(id=3, name="alpine", latitude=50.099, longitude=-122.942, elevation_m=2200),
    ]
    for loc in locations:
        existing = db.get(Location, loc.id)
        if not existing:
            db.add(loc)
    db.flush()
    return locations


@pytest.fixture()
def seed_stations(db):
    """Seed Open-Meteo stations."""
    stations = [
        Station(id=100, source="open_meteo", external_station_id="whistler_base",
                name="Open-Meteo Whistler Base", latitude=50.1145, longitude=-122.954,
                elevation_m=675, is_active=True),
        Station(id=101, source="open_meteo", external_station_id="whistler_alpine",
                name="Open-Meteo Whistler Alpine", latitude=50.099, longitude=-122.942,
                elevation_m=2200, is_active=True),
        Station(id=102, source="eccc", external_station_id="43443",
                name="WHISTLER - NESTERS", latitude=50.1354, longitude=-122.9533,
                elevation_m=659, is_active=True),
    ]
    for stn in stations:
        existing = db.get(Station, stn.id)
        if not existing:
            db.add(stn)
    db.flush()
    return stations


@pytest.fixture()
def seed_forecast_data(db, seed_locations):
    """Seed forecast data. Uses 2099 to avoid conflicts with real data."""
    from datetime import timedelta
    base_time = datetime(2099, 1, 1, tzinfo=timezone.utc)
    run = ForecastRun(
        provider="open_meteo", model_name="gfs_test",
        run_at=base_time,
        fetched_at=base_time + timedelta(days=1),
        raw_payload={"source": "test"},
    )
    db.add(run)
    db.flush()

    for hour in range(48):
        for loc_id in [1, 3]:
            db.add(ForecastValue(
                forecast_run_id=run.id, location_id=loc_id,
                valid_at=base_time + timedelta(hours=hour),
                lead_hours=hour % 24,
                temperature_c=-5.0 + hour * 0.1,
                precip_mm=0.5, snowfall_cm=0.3,
                wind_speed_kmh=20.0 + hour * 0.5,
                wind_gust_kmh=30.0 + hour * 0.5,
                humidity_pct=80.0, pressure_hpa=950.0,
                freezing_level_m=1200.0, weather_code=71,
            ))
    db.flush()
    return run


@pytest.fixture()
def seed_observations(db, seed_stations):
    """Seed observation data. Uses 2099 to avoid conflicts with real data."""
    from datetime import timedelta
    base_time = datetime(2099, 1, 1, tzinfo=timezone.utc)
    for hour in range(48):
        for stn_id in [100, 101]:
            db.add(ObsHourly(
                station_id=stn_id,
                observed_at=base_time + timedelta(hours=hour),
                temperature_c=-3.0 + hour * 0.1,
                precip_mm=0.4, snowfall_cm=0.2,
                snow_depth_cm=50.0, wind_speed_kmh=15.0,
                wind_gust_kmh=25.0, humidity_pct=85.0,
                pressure_hpa=955.0,
            ))
    db.flush()


@pytest.fixture()
def mock_model():
    """Create a mock LightGBM model that returns deterministic predictions."""
    model = MagicMock()
    model.predict = MagicMock(return_value=np.array([1.5] * 24))
    model.best_iteration = 100
    return model

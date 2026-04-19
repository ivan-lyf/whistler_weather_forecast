"""Unit tests for SQLAlchemy ORM models."""

from datetime import datetime, timezone

from app.models.location import Location
from app.models.station import Station
from app.models.observation import ObsHourly
from app.models.forecast import ForecastRun, ForecastValue
from app.models.training_label import TrainingLabel


def test_location_fields():
    loc = Location(name="test", latitude=50.0, longitude=-122.0, elevation_m=1000)
    assert loc.name == "test"
    assert loc.elevation_m == 1000


def test_station_fields():
    stn = Station(source="eccc", external_station_id="123", name="Test",
                  latitude=50.0, longitude=-122.0, is_active=True)
    assert stn.is_active is True
    assert stn.source == "eccc"


def test_obs_hourly_fields():
    obs = ObsHourly(
        station_id=1,
        observed_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        temperature_c=-5.0,
        precip_mm=1.0,
    )
    assert obs.temperature_c == -5.0
    assert obs.snowfall_cm is None  # nullable


def test_forecast_run_fields():
    run = ForecastRun(
        provider="open_meteo", model_name="gfs_seamless",
        run_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        fetched_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
    )
    assert run.provider == "open_meteo"
    assert run.raw_payload is None


def test_forecast_value_fields():
    fv = ForecastValue(
        forecast_run_id=1, location_id=1,
        valid_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        lead_hours=6, temperature_c=-10.0,
        freezing_level_m=800.0, weather_code=71,
    )
    assert fv.lead_hours == 6
    assert fv.weather_code == 71
    assert fv.snowfall_cm is None


def test_training_label_fields():
    tl = TrainingLabel(
        location_id=3,
        target_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        label_24h_snowfall_cm=15.5,
        label_precip_type="snow",
    )
    assert tl.label_24h_snowfall_cm == 15.5
    assert tl.label_precip_type == "snow"
    assert tl.label_6h_wind_kmh is None

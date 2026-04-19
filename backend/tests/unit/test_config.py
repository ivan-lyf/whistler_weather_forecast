"""Unit tests for configuration."""

from app.config import Settings, settings


def test_settings_has_required_fields():
    assert settings.database_url
    assert settings.openmeteo_base_url
    assert settings.openmeteo_archive_url
    assert settings.openmeteo_historical_forecast_url
    assert settings.geomet_base_url


def test_settings_defaults():
    s = Settings(database_url="postgresql+psycopg://test:test@localhost/test")
    assert s.env == "development"
    assert "open-meteo.com" in s.openmeteo_base_url
    assert "archive-api" in s.openmeteo_archive_url
    assert "historical-forecast-api" in s.openmeteo_historical_forecast_url


def test_settings_cors_origins():
    assert settings.cors_origins
    origins = settings.cors_origins.split(",")
    assert len(origins) >= 1


def test_settings_db_pool():
    assert settings.db_pool_size > 0
    assert settings.db_max_overflow > 0
    assert isinstance(settings.db_pool_pre_ping, bool)

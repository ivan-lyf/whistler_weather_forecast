"""Unit tests for feature engineering module."""

import numpy as np
import pandas as pd
import pytest

from scripts.features import (
    build_forecast_features,
    build_cross_elevation_features,
    build_observation_features,
    build_temporal_features,
)


@pytest.fixture()
def sample_forecast_data():
    """48 hours of synthetic forecast data."""
    times = pd.date_range("2025-01-01", periods=48, freq="h", tz="UTC")
    return pd.DataFrame({
        "location_id": 3,
        "valid_at": times,
        "lead_hours": list(range(24)) * 2,
        "temperature_c": np.linspace(-10, 5, 48),
        "precip_mm": np.random.uniform(0, 2, 48),
        "snowfall_cm": np.random.uniform(0, 1, 48),
        "wind_speed_kmh": np.random.uniform(10, 40, 48),
        "wind_gust_kmh": np.random.uniform(20, 60, 48),
        "humidity_pct": np.random.uniform(60, 95, 48),
        "pressure_hpa": np.linspace(950, 960, 48),
        "freezing_level_m": np.linspace(800, 1500, 48),
        "weather_code": [71] * 48,
    })


@pytest.fixture()
def sample_obs_data():
    """48 hours of synthetic observation data."""
    times = pd.date_range("2025-01-01", periods=48, freq="h", tz="UTC")
    return pd.DataFrame({
        "location_id": 3,
        "observed_at": times,
        "temperature_c": np.linspace(-8, 3, 48),
        "precip_mm": np.random.uniform(0, 1.5, 48),
        "snowfall_cm": np.random.uniform(0, 0.8, 48),
        "snow_depth_cm": np.linspace(45, 50, 48),
        "wind_speed_kmh": np.random.uniform(8, 30, 48),
        "wind_gust_kmh": np.random.uniform(15, 50, 48),
        "humidity_pct": np.random.uniform(70, 95, 48),
        "pressure_hpa": np.linspace(955, 965, 48),
    })


def test_forecast_features_shape(sample_forecast_data):
    features = build_forecast_features(sample_forecast_data, location_id=3)
    assert len(features) == 48
    assert "fc_snowfall_24h" in features.columns
    assert "fc_temp_current" in features.columns
    assert "fc_wind_max_6h" in features.columns
    assert "fc_freezing_level" in features.columns
    assert "fc_snow_precip_ratio" in features.columns


def test_forecast_features_rolling_nan(sample_forecast_data):
    """First 23 hours should have NaN for 24h rolling features."""
    features = build_forecast_features(sample_forecast_data, location_id=3)
    assert pd.isna(features["fc_snowfall_24h"].iloc[0])
    assert pd.notna(features["fc_snowfall_24h"].iloc[-1])


def test_forecast_features_non_negative_wind(sample_forecast_data):
    features = build_forecast_features(sample_forecast_data, location_id=3)
    valid = features["fc_wind_max_6h"].dropna()
    assert (valid >= 0).all()


def test_cross_elevation_features(sample_forecast_data):
    base_data = sample_forecast_data.copy()
    base_data["location_id"] = 1
    base_data["temperature_c"] = base_data["temperature_c"] + 5  # warmer at base
    combined = pd.concat([base_data, sample_forecast_data])

    features = build_cross_elevation_features(combined)
    assert "temp_gradient" in features.columns
    assert "fzl_above_alpine" in features.columns
    assert "wind_gradient" in features.columns
    # Alpine should be colder, so gradient should be negative
    valid = features["temp_gradient"].dropna()
    assert (valid < 0).all()


def test_observation_features_shifted(sample_obs_data):
    """All obs features should be shifted to prevent data leakage."""
    features = build_observation_features(sample_obs_data, location_id=3)
    assert "obs_temp_current" in features.columns
    assert "obs_wind_max_6h" in features.columns
    # First value should be NaN due to shift(1)
    assert pd.isna(features["obs_temp_current"].iloc[0])


def test_observation_features_empty():
    """Should handle empty observation data gracefully."""
    empty = pd.DataFrame(columns=[
        "location_id", "observed_at", "temperature_c", "precip_mm",
        "snowfall_cm", "snow_depth_cm", "wind_speed_kmh", "wind_gust_kmh",
        "humidity_pct", "pressure_hpa",
    ])
    # Should not raise — just return empty
    features = build_observation_features(empty, location_id=3)
    assert len(features) == 0


def test_temporal_features():
    idx = pd.date_range("2025-01-15", periods=24, freq="h", tz="UTC")
    features = build_temporal_features(idx)
    assert len(features) == 24
    assert "month" in features.columns
    assert "hour" in features.columns
    assert "is_winter" in features.columns
    assert "month_sin" in features.columns
    # January is winter
    assert (features["is_winter"] == 1).all()
    assert (features["month"] == 1).all()
    assert features["hour"].iloc[0] == 0
    assert features["hour"].iloc[12] == 12


def test_temporal_features_cyclical_range():
    idx = pd.date_range("2025-06-01", periods=24, freq="h", tz="UTC")
    features = build_temporal_features(idx)
    assert features["month_sin"].between(-1, 1).all()
    assert features["month_cos"].between(-1, 1).all()
    assert features["hour_sin"].between(-1, 1).all()
    assert features["hour_cos"].between(-1, 1).all()
    # June is not winter
    assert (features["is_winter"] == 0).all()

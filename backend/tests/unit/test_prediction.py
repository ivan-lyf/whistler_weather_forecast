"""Unit tests for prediction service."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from app.prediction import PRECIP_CLASS_INV, _build_features_inline


@pytest.fixture()
def sample_fc():
    times = pd.date_range("2025-01-01", periods=48, freq="h", tz="UTC")
    return pd.DataFrame({
        "valid_at": times,
        "temperature_c": np.linspace(-5, 5, 48),
        "precip_mm": [0.5] * 48,
        "snowfall_cm": [0.3] * 48,
        "wind_speed_kmh": [20.0] * 48,
        "wind_gust_kmh": [30.0] * 48,
        "humidity_pct": [80.0] * 48,
        "pressure_hpa": [950.0] * 48,
        "freezing_level_m": [1200.0] * 48,
        "weather_code": [71] * 48,
    })


@pytest.fixture()
def sample_obs():
    times = pd.date_range("2025-01-01", periods=48, freq="h", tz="UTC")
    return pd.DataFrame({
        "observed_at": times,
        "temperature_c": np.linspace(-3, 3, 48),
        "precip_mm": [0.4] * 48,
        "snowfall_cm": [0.2] * 48,
        "snow_depth_cm": [50.0] * 48,
        "wind_speed_kmh": [15.0] * 48,
        "wind_gust_kmh": [25.0] * 48,
        "humidity_pct": [85.0] * 48,
        "pressure_hpa": [955.0] * 48,
    })


def test_build_features_inline_returns_dataframe(sample_fc, sample_obs):
    result = _build_features_inline(sample_fc, sample_obs)
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 48


def test_build_features_inline_has_all_groups(sample_fc, sample_obs):
    result = _build_features_inline(sample_fc, sample_obs)
    # Forecast features
    assert "fc_snowfall_24h" in result.columns
    assert "fc_temp_current" in result.columns
    # Observation features
    assert "obs_temp_current" in result.columns
    assert "obs_wind_max_6h" in result.columns
    # Temporal features
    assert "month" in result.columns
    assert "hour_sin" in result.columns
    # Cross-elevation (should be NaN without fc_base)
    assert "temp_gradient" in result.columns


def test_build_features_inline_with_base(sample_fc, sample_obs):
    fc_base = sample_fc.copy()
    fc_base["temperature_c"] = fc_base["temperature_c"] + 5  # warmer
    result = _build_features_inline(sample_fc, sample_obs, fc_base)
    assert result["temp_gradient"].dropna().iloc[0] < 0  # alpine colder


def test_build_features_inline_empty_obs(sample_fc):
    empty_obs = pd.DataFrame(columns=[
        "observed_at", "temperature_c", "precip_mm", "snowfall_cm",
        "snow_depth_cm", "wind_speed_kmh", "wind_gust_kmh",
        "humidity_pct", "pressure_hpa",
    ])
    result = _build_features_inline(sample_fc, empty_obs)
    assert len(result) == 48
    # Obs features should all be NaN
    assert result["obs_temp_current"].isna().all()


def test_precip_class_mapping():
    assert PRECIP_CLASS_INV[0] == "snow"
    assert PRECIP_CLASS_INV[1] == "rain"
    assert PRECIP_CLASS_INV[2] == "mixed"

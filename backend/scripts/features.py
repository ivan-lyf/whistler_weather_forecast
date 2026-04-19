"""Shared feature engineering for all forecast correction models."""

import numpy as np
import pandas as pd


def build_forecast_features(forecasts: pd.DataFrame, location_id: int) -> pd.DataFrame:
    """Build rolling aggregate features from hourly forecast values at a location."""
    fc = forecasts[forecasts["location_id"] == location_id].copy()
    fc = fc.sort_values("valid_at").set_index("valid_at")
    full_idx = pd.date_range(fc.index.min(), fc.index.max(), freq="h", tz="UTC")
    fc = fc.reindex(full_idx)

    features = pd.DataFrame(index=fc.index)

    # Snowfall aggregates
    features["fc_snowfall_24h"] = fc["snowfall_cm"].rolling(24, min_periods=20).sum()
    features["fc_snowfall_6h"] = fc["snowfall_cm"].rolling(6, min_periods=5).sum()
    features["fc_snowfall_12h"] = fc["snowfall_cm"].rolling(12, min_periods=10).sum()

    # Temperature
    features["fc_temp_current"] = fc["temperature_c"]
    features["fc_temp_mean_24h"] = fc["temperature_c"].rolling(24, min_periods=20).mean()
    features["fc_temp_min_24h"] = fc["temperature_c"].rolling(24, min_periods=20).min()
    features["fc_temp_max_24h"] = fc["temperature_c"].rolling(24, min_periods=20).max()

    # Precipitation
    features["fc_precip_24h"] = fc["precip_mm"].rolling(24, min_periods=20).sum()
    features["fc_precip_6h"] = fc["precip_mm"].rolling(6, min_periods=5).sum()

    # Wind
    wind = fc["wind_gust_kmh"].fillna(fc["wind_speed_kmh"])
    features["fc_wind_current"] = wind
    features["fc_wind_speed_current"] = fc["wind_speed_kmh"]
    features["fc_wind_gust_current"] = fc["wind_gust_kmh"]
    features["fc_wind_max_6h"] = wind.rolling(6, min_periods=5).max()
    features["fc_wind_max_12h"] = wind.rolling(12, min_periods=10).max()
    features["fc_wind_max_24h"] = wind.rolling(24, min_periods=20).max()
    features["fc_wind_mean_24h"] = wind.rolling(24, min_periods=20).mean()

    # Humidity and pressure
    features["fc_humidity_current"] = fc["humidity_pct"]
    features["fc_humidity_mean_24h"] = fc["humidity_pct"].rolling(24, min_periods=20).mean()
    features["fc_pressure_current"] = fc["pressure_hpa"]
    features["fc_pressure_mean_24h"] = fc["pressure_hpa"].rolling(24, min_periods=20).mean()
    features["fc_pressure_change_3h"] = fc["pressure_hpa"].diff(3)
    features["fc_pressure_change_6h"] = fc["pressure_hpa"].diff(6)
    features["fc_pressure_change_12h"] = fc["pressure_hpa"].diff(12)

    # Freezing level
    features["fc_freezing_level"] = fc["freezing_level_m"]
    features["fc_freezing_level_mean_24h"] = fc["freezing_level_m"].rolling(24, min_periods=20).mean()
    features["fc_freezing_level_change_6h"] = fc["freezing_level_m"].diff(6)

    # Weather code
    features["fc_weather_code"] = fc["weather_code"]

    # Derived: snow-to-precip ratio (indicator of precip type)
    features["fc_snow_precip_ratio"] = fc["snowfall_cm"] / (fc["precip_mm"].clip(lower=0.01))

    return features


def build_cross_elevation_features(forecasts: pd.DataFrame) -> pd.DataFrame:
    """Build features comparing forecasts across elevation bands."""
    base_fc = forecasts[forecasts["location_id"] == 1].set_index("valid_at").sort_index()
    alpine_fc = forecasts[forecasts["location_id"] == 3].set_index("valid_at").sort_index()

    common_idx = base_fc.index.intersection(alpine_fc.index)
    features = pd.DataFrame(index=common_idx)

    # Temperature gradient (alpine - base)
    features["temp_gradient"] = (
        alpine_fc.loc[common_idx, "temperature_c"] - base_fc.loc[common_idx, "temperature_c"]
    )

    # Snowfall ratio
    base_snow_24 = base_fc.loc[common_idx, "snowfall_cm"].rolling(24, min_periods=20).sum()
    alpine_snow_24 = alpine_fc.loc[common_idx, "snowfall_cm"].rolling(24, min_periods=20).sum()
    features["snow_ratio_alpine_base"] = alpine_snow_24 / base_snow_24.clip(lower=0.01)

    # Freezing level vs elevations
    features["fzl_above_alpine"] = alpine_fc.loc[common_idx, "freezing_level_m"] - 2200
    features["fzl_above_base"] = base_fc.loc[common_idx, "freezing_level_m"] - 675

    # Wind gradient
    base_wind = base_fc.loc[common_idx, "wind_gust_kmh"].fillna(base_fc.loc[common_idx, "wind_speed_kmh"])
    alpine_wind = alpine_fc.loc[common_idx, "wind_gust_kmh"].fillna(alpine_fc.loc[common_idx, "wind_speed_kmh"])
    features["wind_gradient"] = alpine_wind - base_wind

    # Pressure gradient (lower pressure at altitude = stronger instability)
    features["pressure_gradient"] = (
        alpine_fc.loc[common_idx, "pressure_hpa"] - base_fc.loc[common_idx, "pressure_hpa"]
    )

    return features


def build_observation_features(obs: pd.DataFrame, location_id: int) -> pd.DataFrame:
    """Build lagged observation features (what actually happened recently)."""
    ob = obs[obs["location_id"] == location_id].copy()
    if ob.empty:
        return pd.DataFrame()
    ob = ob.sort_values("observed_at").set_index("observed_at")
    full_idx = pd.date_range(ob.index.min(), ob.index.max(), freq="h", tz="UTC")
    ob = ob.reindex(full_idx)

    features = pd.DataFrame(index=ob.index)

    # Lagged snowfall
    features["obs_snowfall_24h_lag24"] = ob["snowfall_cm"].rolling(24, min_periods=20).sum().shift(24)
    features["obs_snowfall_6h_lag6"] = ob["snowfall_cm"].rolling(6, min_periods=5).sum().shift(6)

    # Snow depth
    features["obs_snow_depth"] = ob["snow_depth_cm"].shift(1)

    # Temperature
    features["obs_temp_current"] = ob["temperature_c"].shift(1)
    features["obs_temp_change_3h"] = ob["temperature_c"].diff(3).shift(1)
    features["obs_temp_change_6h"] = ob["temperature_c"].diff(6).shift(1)

    # Pressure (key weather signal)
    features["obs_pressure_current"] = ob["pressure_hpa"].shift(1)
    features["obs_pressure_change_3h"] = ob["pressure_hpa"].diff(3).shift(1)
    features["obs_pressure_change_6h"] = ob["pressure_hpa"].diff(6).shift(1)
    features["obs_pressure_change_12h"] = ob["pressure_hpa"].diff(12).shift(1)

    # Wind
    wind = ob["wind_gust_kmh"].fillna(ob["wind_speed_kmh"])
    features["obs_wind_current"] = wind.shift(1)
    features["obs_wind_max_3h"] = wind.rolling(3, min_periods=2).max().shift(1)
    features["obs_wind_max_6h"] = wind.rolling(6, min_periods=5).max().shift(1)
    features["obs_wind_max_12h"] = wind.rolling(12, min_periods=10).max().shift(1)
    features["obs_wind_mean_6h"] = wind.rolling(6, min_periods=5).mean().shift(1)

    # Humidity
    features["obs_humidity"] = ob["humidity_pct"].shift(1)

    # Precip
    features["obs_precip_6h"] = ob["precip_mm"].rolling(6, min_periods=5).sum().shift(1)

    return features


def build_ensemble_features(gfs_forecasts: pd.DataFrame, ecmwf_forecasts: pd.DataFrame,
                            location_id: int) -> pd.DataFrame:
    """Build features comparing GFS vs ECMWF forecasts (ensemble spread/mean)."""
    gfs = gfs_forecasts[gfs_forecasts["location_id"] == location_id].copy()
    ecmwf = ecmwf_forecasts[ecmwf_forecasts["location_id"] == location_id].copy()

    if gfs.empty or ecmwf.empty:
        return pd.DataFrame()

    gfs = gfs.sort_values("valid_at").set_index("valid_at")
    ecmwf = ecmwf.sort_values("valid_at").set_index("valid_at")
    idx = gfs.index.intersection(ecmwf.index)

    if len(idx) == 0:
        return pd.DataFrame()

    features = pd.DataFrame(index=idx)

    # Per-variable: ECMWF value, ensemble mean, ensemble spread
    for var, name in [
        ("temperature_c", "temp"),
        ("snowfall_cm", "snow"),
        ("precip_mm", "precip"),
        ("wind_speed_kmh", "wind"),
        ("pressure_hpa", "pressure"),
        ("freezing_level_m", "fzl"),
    ]:
        g = gfs.loc[idx, var] if var in gfs.columns else pd.Series(np.nan, index=idx)
        e = ecmwf.loc[idx, var] if var in ecmwf.columns else pd.Series(np.nan, index=idx)

        features[f"ecmwf_{name}"] = e
        features[f"ens_mean_{name}"] = (g + e) / 2
        features[f"ens_spread_{name}"] = (g - e).abs()

    # Rolling ensemble spread (indicates forecast uncertainty over time)
    if "ens_spread_temp" in features.columns:
        features["ens_spread_temp_6h"] = features["ens_spread_temp"].rolling(6, min_periods=4).mean()
        features["ens_spread_snow_24h"] = features["ens_spread_snow"].rolling(24, min_periods=20).mean()

    return features


def simulate_missing_obs(features: pd.DataFrame, missing_rate: float = 0.15,
                         seed: int | None = None) -> pd.DataFrame:
    """Randomly set observation features to NaN during training to match production.

    In production, recent observations may be delayed or missing. This function
    simulates that by randomly masking obs_ columns, so the model learns to
    degrade gracefully instead of overfitting to always-available obs features.
    """
    rng = np.random.RandomState(seed)
    obs_cols = [c for c in features.columns if c.startswith("obs_")]
    if not obs_cols:
        return features

    result = features.copy()
    mask = rng.random(len(result)) < missing_rate
    result.loc[mask, obs_cols] = np.nan
    return result


def build_temporal_features(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Calendar/temporal features."""
    features = pd.DataFrame(index=index)
    features["month"] = index.month
    features["hour"] = index.hour
    features["day_of_year"] = index.dayofyear
    features["is_winter"] = index.month.isin([11, 12, 1, 2, 3, 4]).astype(int)
    features["month_sin"] = np.sin(2 * np.pi * index.month / 12)
    features["month_cos"] = np.cos(2 * np.pi * index.month / 12)
    features["hour_sin"] = np.sin(2 * np.pi * index.hour / 24)
    features["hour_cos"] = np.cos(2 * np.pi * index.hour / 24)
    return features

"""Prediction service: loads trained models and generates predictions from DB data."""

import logging
import pickle
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger("prediction")

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"

PRECIP_CLASSES = ["snow", "rain", "mixed", "none"]
PRECIP_CLASS_INV = {i: c for i, c in enumerate(PRECIP_CLASSES)}

_model_cache: dict = {}


def _load_model(name: str) -> dict:
    if name not in _model_cache:
        path = MODEL_DIR / f"{name}.pkl"
        if not path.exists():
            raise FileNotFoundError(f"Model not found: {path}")
        with open(path, "rb") as f:
            _model_cache[name] = pickle.load(f)
        log.info("Loaded model: %s", name)
    return _model_cache[name]


def _load_forecast_data(db: Session, location_id: int, start: datetime, end: datetime,
                        model_filter: str | None = None) -> pd.DataFrame:
    if model_filter:
        query = """
            SELECT fv.valid_at, fv.temperature_c, fv.precip_mm, fv.snowfall_cm,
                   fv.wind_speed_kmh, fv.wind_gust_kmh, fv.humidity_pct,
                   fv.pressure_hpa, fv.freezing_level_m, fv.weather_code
            FROM forecast_values fv
            JOIN forecast_runs fr ON fr.id = fv.forecast_run_id
            WHERE fr.provider = 'open_meteo' AND fv.location_id = :loc
              AND fr.model_name = :model
              AND fv.valid_at >= :start AND fv.valid_at <= :end
            ORDER BY fv.valid_at
        """
        params = {"loc": location_id, "model": model_filter, "start": start, "end": end}
    else:
        query = """
            SELECT fv.valid_at, fv.temperature_c, fv.precip_mm, fv.snowfall_cm,
                   fv.wind_speed_kmh, fv.wind_gust_kmh, fv.humidity_pct,
                   fv.pressure_hpa, fv.freezing_level_m, fv.weather_code
            FROM forecast_values fv
            JOIN forecast_runs fr ON fr.id = fv.forecast_run_id
            WHERE fr.provider = 'open_meteo' AND fv.location_id = :loc
              AND fv.valid_at >= :start AND fv.valid_at <= :end
            ORDER BY fv.valid_at
        """
        params = {"loc": location_id, "start": start, "end": end}

    rows = db.execute(text(query), params).all()
    df = pd.DataFrame(rows, columns=[
        "valid_at", "temperature_c", "precip_mm", "snowfall_cm",
        "wind_speed_kmh", "wind_gust_kmh", "humidity_pct",
        "pressure_hpa", "freezing_level_m", "weather_code",
    ])
    df["valid_at"] = pd.to_datetime(df["valid_at"], utc=True)
    df = df.drop_duplicates(subset=["valid_at"], keep="last")
    return df


def _load_obs_data(db: Session, station_ext_id: str, start: datetime, end: datetime) -> pd.DataFrame:
    rows = db.execute(text("""
        SELECT o.observed_at, o.temperature_c, o.precip_mm, o.snowfall_cm,
               o.snow_depth_cm, o.wind_speed_kmh, o.wind_gust_kmh,
               o.humidity_pct, o.pressure_hpa
        FROM obs_hourly o JOIN stations s ON s.id = o.station_id
        WHERE s.external_station_id = :sid
          AND o.observed_at >= :start AND o.observed_at <= :end
        ORDER BY o.observed_at
    """), {"sid": station_ext_id, "start": start, "end": end}).all()
    df = pd.DataFrame(rows, columns=[
        "observed_at", "temperature_c", "precip_mm", "snowfall_cm",
        "snow_depth_cm", "wind_speed_kmh", "wind_gust_kmh",
        "humidity_pct", "pressure_hpa",
    ])
    df["observed_at"] = pd.to_datetime(df["observed_at"], utc=True)
    return df


def _build_features_inline(fc: pd.DataFrame, obs: pd.DataFrame,
                           fc_base: pd.DataFrame | None = None,
                           fc_ecmwf: pd.DataFrame | None = None) -> pd.DataFrame:
    """Feature builder matching the training pipeline, including ensemble features."""
    fc = fc.sort_values("valid_at").set_index("valid_at")
    idx = pd.date_range(fc.index.min(), fc.index.max(), freq="h", tz="UTC")
    fc = fc.reindex(idx)

    f = pd.DataFrame(index=idx)

    # Forecast features
    f["fc_snowfall_24h"] = fc["snowfall_cm"].rolling(24, min_periods=20).sum()
    f["fc_snowfall_6h"] = fc["snowfall_cm"].rolling(6, min_periods=5).sum()
    f["fc_snowfall_12h"] = fc["snowfall_cm"].rolling(12, min_periods=10).sum()
    f["fc_temp_current"] = fc["temperature_c"]
    f["fc_temp_mean_24h"] = fc["temperature_c"].rolling(24, min_periods=20).mean()
    f["fc_temp_min_24h"] = fc["temperature_c"].rolling(24, min_periods=20).min()
    f["fc_temp_max_24h"] = fc["temperature_c"].rolling(24, min_periods=20).max()
    f["fc_precip_24h"] = fc["precip_mm"].rolling(24, min_periods=20).sum()
    f["fc_precip_6h"] = fc["precip_mm"].rolling(6, min_periods=5).sum()

    wind = fc["wind_gust_kmh"].fillna(fc["wind_speed_kmh"])
    f["fc_wind_current"] = wind
    f["fc_wind_speed_current"] = fc["wind_speed_kmh"]
    f["fc_wind_gust_current"] = fc["wind_gust_kmh"]
    f["fc_wind_max_6h"] = wind.rolling(6, min_periods=5).max()
    f["fc_wind_max_12h"] = wind.rolling(12, min_periods=10).max()
    f["fc_wind_max_24h"] = wind.rolling(24, min_periods=20).max()
    f["fc_wind_mean_24h"] = wind.rolling(24, min_periods=20).mean()

    f["fc_humidity_current"] = fc["humidity_pct"]
    f["fc_humidity_mean_24h"] = fc["humidity_pct"].rolling(24, min_periods=20).mean()
    f["fc_pressure_current"] = fc["pressure_hpa"]
    f["fc_pressure_mean_24h"] = fc["pressure_hpa"].rolling(24, min_periods=20).mean()
    f["fc_pressure_change_3h"] = fc["pressure_hpa"].diff(3)
    f["fc_pressure_change_6h"] = fc["pressure_hpa"].diff(6)
    f["fc_pressure_change_12h"] = fc["pressure_hpa"].diff(12)

    f["fc_freezing_level"] = fc["freezing_level_m"]
    f["fc_freezing_level_mean_24h"] = fc["freezing_level_m"].rolling(24, min_periods=20).mean()
    f["fc_freezing_level_change_6h"] = fc["freezing_level_m"].diff(6)
    f["fc_weather_code"] = fc["weather_code"]
    f["fc_snow_precip_ratio"] = fc["snowfall_cm"] / fc["precip_mm"].clip(lower=0.01)

    # Cross-elevation (if base data provided)
    if fc_base is not None:
        fb = fc_base.sort_values("valid_at").set_index("valid_at").reindex(idx)
        f["temp_gradient"] = fc["temperature_c"] - fb["temperature_c"]
        base_s24 = fb["snowfall_cm"].rolling(24, min_periods=20).sum()
        alp_s24 = fc["snowfall_cm"].rolling(24, min_periods=20).sum()
        f["snow_ratio_alpine_base"] = alp_s24 / base_s24.clip(lower=0.01)
        f["fzl_above_alpine"] = fc["freezing_level_m"] - 2200
        f["fzl_above_base"] = fb["freezing_level_m"] - 675
        bw = fb["wind_gust_kmh"].fillna(fb["wind_speed_kmh"])
        aw = fc["wind_gust_kmh"].fillna(fc["wind_speed_kmh"])
        f["wind_gradient"] = aw - bw
        f["pressure_gradient"] = fc["pressure_hpa"] - fb["pressure_hpa"]
    else:
        for col in ["temp_gradient", "snow_ratio_alpine_base", "fzl_above_alpine",
                     "fzl_above_base", "wind_gradient", "pressure_gradient"]:
            f[col] = np.nan

    # Observation features
    if not obs.empty:
        ob = obs.sort_values("observed_at").set_index("observed_at").reindex(idx)
        f["obs_snowfall_24h_lag24"] = ob["snowfall_cm"].rolling(24, min_periods=20).sum().shift(24)
        f["obs_snowfall_6h_lag6"] = ob["snowfall_cm"].rolling(6, min_periods=5).sum().shift(6)
        f["obs_snow_depth"] = ob["snow_depth_cm"].shift(1)
        f["obs_temp_current"] = ob["temperature_c"].shift(1)
        f["obs_temp_change_3h"] = ob["temperature_c"].diff(3).shift(1)
        f["obs_temp_change_6h"] = ob["temperature_c"].diff(6).shift(1)
        f["obs_pressure_current"] = ob["pressure_hpa"].shift(1)
        f["obs_pressure_change_3h"] = ob["pressure_hpa"].diff(3).shift(1)
        f["obs_pressure_change_6h"] = ob["pressure_hpa"].diff(6).shift(1)
        f["obs_pressure_change_12h"] = ob["pressure_hpa"].diff(12).shift(1)
        ow = ob["wind_gust_kmh"].fillna(ob["wind_speed_kmh"])
        f["obs_wind_current"] = ow.shift(1)
        f["obs_wind_max_3h"] = ow.rolling(3, min_periods=2).max().shift(1)
        f["obs_wind_max_6h"] = ow.rolling(6, min_periods=5).max().shift(1)
        f["obs_wind_max_12h"] = ow.rolling(12, min_periods=10).max().shift(1)
        f["obs_wind_mean_6h"] = ow.rolling(6, min_periods=5).mean().shift(1)
        f["obs_humidity"] = ob["humidity_pct"].shift(1)
        f["obs_precip_6h"] = ob["precip_mm"].rolling(6, min_periods=5).sum().shift(1)
    else:
        for col in ["obs_snowfall_24h_lag24", "obs_snowfall_6h_lag6", "obs_snow_depth",
                     "obs_temp_current", "obs_temp_change_3h", "obs_temp_change_6h",
                     "obs_pressure_current", "obs_pressure_change_3h",
                     "obs_pressure_change_6h", "obs_pressure_change_12h",
                     "obs_wind_current", "obs_wind_max_3h", "obs_wind_max_6h",
                     "obs_wind_max_12h", "obs_wind_mean_6h", "obs_humidity", "obs_precip_6h"]:
            f[col] = np.nan

    # Ensemble features (GFS vs ECMWF)
    if fc_ecmwf is not None and not fc_ecmwf.empty:
        ec = fc_ecmwf.sort_values("valid_at").set_index("valid_at").reindex(idx)
        for var, name in [
            ("temperature_c", "temp"), ("snowfall_cm", "snow"), ("precip_mm", "precip"),
            ("wind_speed_kmh", "wind"), ("pressure_hpa", "pressure"), ("freezing_level_m", "fzl"),
        ]:
            g = fc[var] if var in fc.columns else pd.Series(np.nan, index=idx)
            e = ec[var] if var in ec.columns else pd.Series(np.nan, index=idx)
            f[f"ecmwf_{name}"] = e
            f[f"ens_mean_{name}"] = (g + e) / 2
            f[f"ens_spread_{name}"] = (g - e).abs()
        if "ens_spread_temp" in f.columns:
            f["ens_spread_temp_6h"] = f["ens_spread_temp"].rolling(6, min_periods=4).mean()
            f["ens_spread_snow_24h"] = f["ens_spread_snow"].rolling(24, min_periods=20).mean()
    else:
        for name in ["temp", "snow", "precip", "wind", "pressure", "fzl"]:
            f[f"ecmwf_{name}"] = np.nan
            f[f"ens_mean_{name}"] = np.nan
            f[f"ens_spread_{name}"] = np.nan
        f["ens_spread_temp_6h"] = np.nan
        f["ens_spread_snow_24h"] = np.nan

    # Temporal
    f["month"] = idx.month
    f["hour"] = idx.hour
    f["day_of_year"] = idx.dayofyear
    f["is_winter"] = idx.month.isin([11, 12, 1, 2, 3, 4]).astype(int)
    f["month_sin"] = np.sin(2 * np.pi * idx.month / 12)
    f["month_cos"] = np.cos(2 * np.pi * idx.month / 12)
    f["hour_sin"] = np.sin(2 * np.pi * idx.hour / 24)
    f["hour_cos"] = np.cos(2 * np.pi * idx.hour / 24)

    return f


LOC_STATION_MAP = {
    1: "whistler_base",
    2: "whistler_mid",
    3: "whistler_alpine",
}

LOC_NAMES = {1: "base", 2: "mid", 3: "alpine"}


def _predict_for_location(
    db: Session, loc_id: int, start: datetime, end: datetime,
    fc_base: pd.DataFrame, obs_base: pd.DataFrame,
) -> list[dict]:
    """Generate predictions for a single location."""
    from datetime import timedelta
    buf_start = start - timedelta(hours=48)

    loc_name = LOC_NAMES[loc_id]
    station_id = LOC_STATION_MAP[loc_id]

    # Load GFS + ECMWF forecast data
    fc_gfs = _load_forecast_data(db, loc_id, buf_start, end, model_filter="gfs_seamless")
    fc_live = _load_forecast_data(db, loc_id, buf_start, end, model_filter="gfs_live")
    fc = pd.concat([fc_gfs, fc_live]).drop_duplicates(subset=["valid_at"], keep="last") if not fc_live.empty else fc_gfs

    fc_ecmwf_hist = _load_forecast_data(db, loc_id, buf_start, end, model_filter="ecmwf_ifs025")
    fc_ecmwf_live = _load_forecast_data(db, loc_id, buf_start, end, model_filter="ecmwf_live")
    fc_ecmwf = pd.concat([fc_ecmwf_hist, fc_ecmwf_live]).drop_duplicates(subset=["valid_at"], keep="last") if not fc_ecmwf_live.empty else fc_ecmwf_hist

    obs = _load_obs_data(db, station_id, buf_start, end)

    if fc.empty:
        return []

    # Cross-elevation: always compare against base
    fc_base_ref = fc_base if loc_id != 1 else None
    features = _build_features_inline(fc, obs, fc_base_ref, fc_ecmwf=fc_ecmwf)

    idx = features.loc[start:end].index
    results = []

    # Temperature (raw forecast — no ML model needed)
    try:
        fc_sorted = fc.sort_values("valid_at").set_index("valid_at").reindex(features.index)
        for t in idx:
            temp = fc_sorted.loc[t, "temperature_c"] if t in fc_sorted.index else None
            if temp is not None and not pd.isna(temp):
                results.append({"time": t.isoformat(), "target": "temperature",
                                "location": loc_name, "value": round(float(temp), 1), "unit": "°C"})
    except Exception as e:
        log.warning("Temperature extraction failed for %s: %s", loc_name, e)

    # Snowfall
    try:
        m = _load_model("snowfall_24h_alpine")
        X = features.loc[idx, m["feature_cols"]]
        preds = np.clip(m["model"].predict(X, num_iteration=m["best_iteration"]), 0, None)
        for t, v in zip(idx, preds):
            results.append({"time": t.isoformat(), "target": "snowfall_24h",
                            "location": loc_name, "value": round(float(v), 2), "unit": "cm"})
    except Exception as e:
        log.warning("Snowfall prediction failed for %s: %s", loc_name, e)

    # Wind 6h
    try:
        m = _load_model("wind_6h_alpine")
        X = features.loc[idx, m["feature_cols"]]
        preds = np.clip(m["model"].predict(X, num_iteration=m["best_iteration"]), 0, None)
        for t, v in zip(idx, preds):
            results.append({"time": t.isoformat(), "target": "wind_6h",
                            "location": loc_name, "value": round(float(v), 1), "unit": "km/h"})
    except Exception as e:
        log.warning("Wind 6h prediction failed for %s: %s", loc_name, e)

    # Wind 12h
    try:
        m = _load_model("wind_12h_alpine")
        X = features.loc[idx, m["feature_cols"]]
        preds = np.clip(m["model"].predict(X, num_iteration=m["best_iteration"]), 0, None)
        for t, v in zip(idx, preds):
            results.append({"time": t.isoformat(), "target": "wind_12h",
                            "location": loc_name, "value": round(float(v), 1), "unit": "km/h"})
    except Exception as e:
        log.warning("Wind 12h prediction failed for %s: %s", loc_name, e)

    # Freezing level (use base features — freezing level is location-independent)
    try:
        m = _load_model("freezing_level_base")
        features_base = _build_features_inline(fc_base, obs_base)
        X = features_base.loc[idx, m["feature_cols"]]
        preds = np.clip(m["model"].predict(X, num_iteration=m["best_iteration"]), 0, 5000)
        for t, v in zip(idx, preds):
            results.append({"time": t.isoformat(), "target": "freezing_level",
                            "location": loc_name, "value": round(float(v), 0), "unit": "m"})
    except Exception as e:
        log.warning("Freezing level prediction failed for %s: %s", loc_name, e)

    # Precip type
    try:
        m = _load_model("precip_type_alpine")
        X = features.loc[idx, m["feature_cols"]]
        raw_preds = m["model"].predict(X, num_iteration=m["best_iteration"])
        pred_classes = raw_preds.argmax(axis=1)
        confidences = raw_preds.max(axis=1)
        for t, cls, conf in zip(idx, pred_classes, confidences):
            results.append({"time": t.isoformat(), "target": "precip_type",
                            "location": loc_name, "value": PRECIP_CLASS_INV[cls],
                            "confidence": round(float(conf), 3), "unit": ""})
    except Exception as e:
        log.warning("Precip type prediction failed for %s: %s", loc_name, e)

    return results


def get_predictions(db: Session, start: datetime, end: datetime,
                    location: str | None = None) -> list[dict]:
    """Generate predictions for all models over a time range."""
    from datetime import timedelta
    buf_start = start - timedelta(hours=48)

    # Always load base data (needed for cross-elevation features and freezing level)
    fc_base = _load_forecast_data(db, 1, buf_start, end)
    obs_base = _load_obs_data(db, "whistler_base", buf_start, end)

    if location:
        loc_ids = {"base": 1, "mid": 2, "alpine": 3}
        loc_id = loc_ids.get(location, 3)
        return _predict_for_location(db, loc_id, start, end, fc_base, obs_base)

    # All locations
    results = []
    for loc_id in [1, 2, 3]:
        results.extend(_predict_for_location(db, loc_id, start, end, fc_base, obs_base))
    return results


def get_comparison(db: Session, start: datetime, end: datetime,
                   location: str = "alpine") -> list[dict]:
    """Return raw GFS forecast vs corrected predictions vs observations."""
    from datetime import timedelta
    buf_start = start - timedelta(hours=48)

    loc_ids = {"base": 1, "mid": 2, "alpine": 3}
    loc_id = loc_ids.get(location, 3)
    station_id = LOC_STATION_MAP[loc_id]

    fc = _load_forecast_data(db, loc_id, buf_start, end)
    obs = _load_obs_data(db, station_id, start, end)

    if fc.empty:
        return []

    fc_idx = fc.set_index("valid_at").sort_index()
    idx = pd.date_range(start, end, freq="h", tz="UTC")
    fc_idx = fc_idx.reindex(idx)

    # Raw GFS 24h snowfall
    raw_snow_24h = fc_idx["snowfall_cm"].rolling(24, min_periods=20).sum()

    # Observations
    obs_idx = obs.set_index("observed_at").reindex(idx) if not obs.empty else pd.DataFrame(index=idx)
    obs_snow_24h = obs_idx["snowfall_cm"].rolling(24, min_periods=20).sum() if "snowfall_cm" in obs_idx.columns else pd.Series(np.nan, index=idx)

    # Corrected predictions
    predictions = get_predictions(db, start, end, location=location)
    corrected = {p["time"]: p["value"] for p in predictions if p["target"] == "snowfall_24h"}

    results = []
    for t in idx:
        results.append({
            "time": t.isoformat(),
            "raw_gfs_snowfall_cm": round(float(raw_snow_24h.get(t, np.nan)), 2) if pd.notna(raw_snow_24h.get(t, np.nan)) else None,
            "corrected_snowfall_cm": corrected.get(t.isoformat()),
            "observed_snowfall_cm": round(float(obs_snow_24h.get(t, np.nan)), 2) if pd.notna(obs_snow_24h.get(t, np.nan)) else None,
        })
    return results


def get_forecast_summary(db: Session, location: str = "alpine") -> dict:
    """Single-call summary optimized for the skier dashboard hero page."""
    from datetime import timedelta

    loc_ids = {"base": 1, "mid": 2, "alpine": 3}
    loc_id = loc_ids.get(location, 3)
    station_id = LOC_STATION_MAP.get(loc_id, "whistler_alpine")

    now = datetime.now(timezone.utc)
    buf_start = now - timedelta(hours=48)
    end = now + timedelta(hours=48)

    fc = _load_forecast_data(db, loc_id, buf_start, end)
    if fc.empty:
        return {"error": "No forecast data available"}

    fc = fc.sort_values("valid_at").set_index("valid_at")
    full_idx = pd.date_range(fc.index.min(), fc.index.max(), freq="h", tz="UTC")
    fc = fc.reindex(full_idx)

    # Find the closest hour to now
    future = fc.loc[now:]
    if future.empty:
        return {"error": "No future forecast data"}

    # Temperature
    temp_now = future["temperature_c"].iloc[0] if not future.empty else None
    future_24h = future.iloc[:24]
    temp_high = future_24h["temperature_c"].max() if len(future_24h) > 0 else None
    temp_low = future_24h["temperature_c"].min() if len(future_24h) > 0 else None

    # Snowfall accumulations (sum of hourly snowfall over window)
    snow_6h = future.iloc[:6]["snowfall_cm"].sum() if len(future) >= 6 else future["snowfall_cm"].sum()
    snow_12h = future.iloc[:12]["snowfall_cm"].sum() if len(future) >= 12 else future["snowfall_cm"].sum()
    snow_24h = future.iloc[:24]["snowfall_cm"].sum() if len(future) >= 24 else future["snowfall_cm"].sum()

    # Wind
    wind = future["wind_gust_kmh"].fillna(future["wind_speed_kmh"])
    wind_now = wind.iloc[0] if len(wind) > 0 else None
    wind_peak_6h = wind.iloc[:6].max() if len(wind) >= 6 else wind.max()
    wind_risk = "HIGH" if wind_peak_6h and wind_peak_6h > 50 else "MODERATE" if wind_peak_6h and wind_peak_6h > 30 else "LOW"

    # Freezing level + precip type from pre-computed predictions (faster, uses ensemble features)
    from app.models.model_prediction import ModelPrediction
    from sqlalchemy import select as sa_select
    preds_rows = db.execute(
        sa_select(ModelPrediction).where(
            ModelPrediction.location_id == loc_id,
            ModelPrediction.target_time >= now,
            ModelPrediction.target_time <= now + timedelta(hours=6),
        )
    ).scalars().all()
    preds = [
        {"target": r.target_name, "value": r.predicted_value if r.predicted_value is not None else r.predicted_class,
         "confidence": r.confidence}
        for r in preds_rows
    ]
    fzl_vals = [p["value"] for p in preds if p["target"] == "freezing_level" and isinstance(p["value"], (int, float))]
    precip_vals = [p for p in preds if p["target"] == "precip_type"]

    freezing_level = round(float(fzl_vals[0])) if fzl_vals else None

    precip_type = None
    precip_confidence = None
    if precip_vals:
        # Most common type in next 6h
        types = [p["value"] for p in precip_vals if isinstance(p["value"], str)]
        if types:
            from collections import Counter
            precip_type = Counter(types).most_common(1)[0][0]
        confs = [p.get("confidence") for p in precip_vals if p.get("confidence")]
        precip_confidence = round(sum(confs) / len(confs), 2) if confs else None

    # Last updated
    last_run = db.execute(text(
        "SELECT MAX(run_at) FROM forecast_runs WHERE model_name IN ('gfs_live','ecmwf_live')"
    )).scalar()

    def _round(v, n=1):
        return round(float(v), n) if v is not None and not pd.isna(v) else None

    return {
        "location": location,
        "snowfall_6h": _round(snow_6h),
        "snowfall_12h": _round(snow_12h),
        "snowfall_24h": _round(snow_24h),
        "temp_now": _round(temp_now),
        "temp_high_24h": _round(temp_high),
        "temp_low_24h": _round(temp_low),
        "wind_now": _round(wind_now),
        "wind_peak_6h": _round(wind_peak_6h),
        "wind_risk": wind_risk,
        "precip_type": precip_type,
        "precip_confidence": precip_confidence,
        "freezing_level": freezing_level,
        "last_updated": last_run.isoformat() if last_run else None,
    }


def get_metrics_summary(db: Session) -> dict:
    """Return model performance metrics from pre-computed reports."""
    import json
    reports_dir = Path(__file__).resolve().parent.parent
    metrics = {}
    for name in ["snowfall_model", "wind_6h", "wind_12h", "freezing_level", "precip_type", "baseline"]:
        path = reports_dir / f"{name}_report.json"
        if path.exists():
            with open(path) as f:
                metrics[name] = json.load(f)
    return metrics

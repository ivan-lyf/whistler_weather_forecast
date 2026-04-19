"""Train a LightGBM model for 24h alpine snowfall correction.

This is the Week 5 deliverable: the first ML correction model.
Target: Beat the raw GFS baseline MAE of 1.742 cm on the test period.
"""

import json
import logging
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal

log = logging.getLogger("train_snowfall")

# Rolling time splits
TRAIN_END = "2024-12-31"
VALIDATE_START = "2025-01-01"
VALIDATE_END = "2025-06-30"
TEST_START = "2025-07-01"
TEST_END = "2025-12-31"

# Target
TARGET_COL = "label_24h_snowfall_cm"
ALPINE_LOCATION_ID = 3

MODEL_DIR = Path(__file__).parent.parent / "models"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_all_data(db) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load labels, forecasts, and observations into DataFrames."""

    # Labels
    labels = pd.DataFrame(
        db.execute(text("""
            SELECT tl.location_id, l.name as location_name, tl.target_time,
                   tl.label_24h_snowfall_cm, tl.label_6h_wind_kmh,
                   tl.label_12h_wind_kmh, tl.label_freezing_level_m
            FROM training_labels tl
            JOIN locations l ON l.id = tl.location_id
            ORDER BY tl.location_id, tl.target_time
        """)).all(),
        columns=["location_id", "location_name", "target_time",
                 "label_24h_snowfall_cm", "label_6h_wind_kmh",
                 "label_12h_wind_kmh", "label_freezing_level_m"],
    )
    labels["target_time"] = pd.to_datetime(labels["target_time"], utc=True)

    # Forecasts (all 3 locations)
    forecasts = pd.DataFrame(
        db.execute(text("""
            SELECT fv.location_id, fv.valid_at, fv.lead_hours,
                   fv.temperature_c, fv.precip_mm, fv.snowfall_cm,
                   fv.wind_speed_kmh, fv.wind_gust_kmh, fv.humidity_pct,
                   fv.pressure_hpa, fv.freezing_level_m, fv.weather_code
            FROM forecast_values fv
            JOIN forecast_runs fr ON fr.id = fv.forecast_run_id
            WHERE fr.provider = 'open_meteo'
            ORDER BY fv.location_id, fv.valid_at
        """)).all(),
        columns=["location_id", "valid_at", "lead_hours",
                 "temperature_c", "precip_mm", "snowfall_cm",
                 "wind_speed_kmh", "wind_gust_kmh", "humidity_pct",
                 "pressure_hpa", "freezing_level_m", "weather_code"],
    )
    forecasts["valid_at"] = pd.to_datetime(forecasts["valid_at"], utc=True)

    # Observations (Open-Meteo, all 3 elevation stations)
    obs = pd.DataFrame(
        db.execute(text("""
            SELECT s.external_station_id, o.observed_at,
                   o.temperature_c, o.precip_mm, o.snowfall_cm,
                   o.snow_depth_cm, o.wind_speed_kmh, o.wind_gust_kmh,
                   o.humidity_pct, o.pressure_hpa
            FROM obs_hourly o
            JOIN stations s ON s.id = o.station_id
            WHERE s.source = 'open_meteo'
            ORDER BY s.external_station_id, o.observed_at
        """)).all(),
        columns=["station_id", "observed_at", "temperature_c", "precip_mm",
                 "snowfall_cm", "snow_depth_cm", "wind_speed_kmh",
                 "wind_gust_kmh", "humidity_pct", "pressure_hpa"],
    )
    obs["observed_at"] = pd.to_datetime(obs["observed_at"], utc=True)
    station_map = {"whistler_base": 1, "whistler_mid": 2, "whistler_alpine": 3}
    obs["location_id"] = obs["station_id"].map(station_map)

    return labels, forecasts, obs


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------


def build_forecast_features(forecasts: pd.DataFrame, location_id: int) -> pd.DataFrame:
    """Build rolling aggregate features from hourly forecast values at a location."""
    fc = forecasts[forecasts["location_id"] == location_id].copy()
    fc = fc.sort_values("valid_at").set_index("valid_at")
    full_idx = pd.date_range(fc.index.min(), fc.index.max(), freq="h", tz="UTC")
    fc = fc.reindex(full_idx)

    features = pd.DataFrame(index=fc.index)

    # 24h forecast snowfall sum (this is the raw GFS prediction)
    features["fc_snowfall_24h"] = fc["snowfall_cm"].rolling(24, min_periods=20).sum()

    # Shorter windows for recent trend
    features["fc_snowfall_6h"] = fc["snowfall_cm"].rolling(6, min_periods=5).sum()
    features["fc_snowfall_12h"] = fc["snowfall_cm"].rolling(12, min_periods=10).sum()

    # Temperature stats
    features["fc_temp_mean_24h"] = fc["temperature_c"].rolling(24, min_periods=20).mean()
    features["fc_temp_min_24h"] = fc["temperature_c"].rolling(24, min_periods=20).min()
    features["fc_temp_current"] = fc["temperature_c"]

    # Precipitation total
    features["fc_precip_24h"] = fc["precip_mm"].rolling(24, min_periods=20).sum()

    # Wind
    wind = fc["wind_gust_kmh"].fillna(fc["wind_speed_kmh"])
    features["fc_wind_max_6h"] = wind.rolling(6, min_periods=5).max()
    features["fc_wind_max_24h"] = wind.rolling(24, min_periods=20).max()
    features["fc_wind_mean_24h"] = wind.rolling(24, min_periods=20).mean()

    # Humidity and pressure
    features["fc_humidity_mean_24h"] = fc["humidity_pct"].rolling(24, min_periods=20).mean()
    features["fc_pressure_mean_24h"] = fc["pressure_hpa"].rolling(24, min_periods=20).mean()
    features["fc_pressure_change_6h"] = fc["pressure_hpa"].diff(6)

    # Freezing level
    features["fc_freezing_level"] = fc["freezing_level_m"]
    features["fc_freezing_level_mean_24h"] = fc["freezing_level_m"].rolling(24, min_periods=20).mean()

    # Weather code (mode over last 6h — approximate via last value)
    features["fc_weather_code"] = fc["weather_code"]

    return features


def build_cross_elevation_features(forecasts: pd.DataFrame) -> pd.DataFrame:
    """Build features comparing forecasts across elevation bands."""
    base_fc = forecasts[forecasts["location_id"] == 1].set_index("valid_at").sort_index()
    alpine_fc = forecasts[forecasts["location_id"] == 3].set_index("valid_at").sort_index()

    # Align indices
    common_idx = base_fc.index.intersection(alpine_fc.index)

    features = pd.DataFrame(index=common_idx)

    # Temperature gradient
    features["temp_gradient"] = alpine_fc.loc[common_idx, "temperature_c"] - base_fc.loc[common_idx, "temperature_c"]

    # Snowfall ratio: alpine vs base
    base_snow_24 = base_fc.loc[common_idx, "snowfall_cm"].rolling(24, min_periods=20).sum()
    alpine_snow_24 = alpine_fc.loc[common_idx, "snowfall_cm"].rolling(24, min_periods=20).sum()
    features["snow_ratio_alpine_base"] = (alpine_snow_24 / base_snow_24.clip(lower=0.01))

    # Freezing level vs alpine elevation
    features["fzl_above_alpine"] = alpine_fc.loc[common_idx, "freezing_level_m"] - 2200

    return features


def build_observation_features(obs: pd.DataFrame, location_id: int) -> pd.DataFrame:
    """Build lagged observation features (what actually happened recently)."""
    ob = obs[obs["location_id"] == location_id].copy()
    ob = ob.sort_values("observed_at").set_index("observed_at")
    full_idx = pd.date_range(ob.index.min(), ob.index.max(), freq="h", tz="UTC")
    ob = ob.reindex(full_idx)

    features = pd.DataFrame(index=ob.index)

    # Lagged observed snowfall (what happened in the past — shifted to avoid leakage)
    obs_snow_24h = ob["snowfall_cm"].rolling(24, min_periods=20).sum()
    features["obs_snowfall_24h_lag24"] = obs_snow_24h.shift(24)  # yesterday's total
    features["obs_snowfall_6h_lag6"] = ob["snowfall_cm"].rolling(6, min_periods=5).sum().shift(6)

    # Snow depth (cumulative measure)
    features["obs_snow_depth"] = ob["snow_depth_cm"].shift(1)

    # Temperature trend
    features["obs_temp_current"] = ob["temperature_c"].shift(1)
    features["obs_temp_change_6h"] = ob["temperature_c"].diff(6).shift(1)

    # Pressure trend (strong signal for incoming weather)
    features["obs_pressure_current"] = ob["pressure_hpa"].shift(1)
    features["obs_pressure_change_6h"] = ob["pressure_hpa"].diff(6).shift(1)
    features["obs_pressure_change_12h"] = ob["pressure_hpa"].diff(12).shift(1)

    # Wind
    wind = ob["wind_gust_kmh"].fillna(ob["wind_speed_kmh"])
    features["obs_wind_max_6h"] = wind.rolling(6, min_periods=5).max().shift(1)

    # Humidity
    features["obs_humidity"] = ob["humidity_pct"].shift(1)

    return features


def build_temporal_features(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Calendar/temporal features."""
    features = pd.DataFrame(index=index)
    features["month"] = index.month
    features["hour"] = index.hour
    features["day_of_year"] = index.dayofyear
    features["is_winter"] = index.month.isin([11, 12, 1, 2, 3, 4]).astype(int)
    # Cyclical encoding
    features["month_sin"] = np.sin(2 * np.pi * index.month / 12)
    features["month_cos"] = np.cos(2 * np.pi * index.month / 12)
    features["hour_sin"] = np.sin(2 * np.pi * index.hour / 24)
    features["hour_cos"] = np.cos(2 * np.pi * index.hour / 24)
    return features


def build_feature_matrix(labels: pd.DataFrame, forecasts: pd.DataFrame,
                         obs: pd.DataFrame) -> pd.DataFrame:
    """Build the full feature matrix for alpine snowfall prediction."""
    # Filter to alpine labels
    alpine_labels = labels[labels["location_id"] == ALPINE_LOCATION_ID].copy()
    alpine_labels = alpine_labels.set_index("target_time")

    log.info("Building forecast features (alpine)...")
    fc_features = build_forecast_features(forecasts, ALPINE_LOCATION_ID)

    log.info("Building cross-elevation features...")
    cross_features = build_cross_elevation_features(forecasts)

    log.info("Building observation features (alpine)...")
    obs_features = build_observation_features(obs, ALPINE_LOCATION_ID)

    log.info("Building temporal features...")
    temporal_features = build_temporal_features(alpine_labels.index)

    # Join everything on the label index (target_time)
    df = alpine_labels[[TARGET_COL]].copy()
    df = df.join(fc_features, how="left")
    df = df.join(cross_features, how="left")
    df = df.join(obs_features, how="left")
    df = df.join(temporal_features, how="left")

    log.info("Feature matrix: %d rows, %d columns (before dropping NaN target)",
             len(df), len(df.columns))

    # Drop rows where target is NaN
    df = df.dropna(subset=[TARGET_COL])

    log.info("After dropping NaN target: %d rows", len(df))
    return df


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def train_and_evaluate(df: pd.DataFrame) -> dict:
    """Train LightGBM and evaluate on rolling splits."""
    feature_cols = [c for c in df.columns if c != TARGET_COL]

    # Split by time
    train = df[df.index <= TRAIN_END]
    validate = df[(df.index >= VALIDATE_START) & (df.index <= VALIDATE_END)]
    test = df[(df.index >= TEST_START) & (df.index <= TEST_END)]

    log.info("Split sizes — train: %d, validate: %d, test: %d",
             len(train), len(validate), len(test))

    X_train, y_train = train[feature_cols], train[TARGET_COL]
    X_val, y_val = validate[feature_cols], validate[TARGET_COL]
    X_test, y_test = test[feature_cols], test[TARGET_COL]

    # LightGBM datasets
    dtrain = lgb.Dataset(X_train, label=y_train)
    dval = lgb.Dataset(X_val, label=y_val, reference=dtrain)

    params = {
        "objective": "regression",
        "metric": ["mae", "rmse"],
        "learning_rate": 0.05,
        "num_leaves": 31,
        "max_depth": 6,
        "min_child_samples": 20,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "reg_alpha": 0.1,
        "reg_lambda": 0.1,
        "verbosity": -1,
    }

    log.info("Training LightGBM...")
    callbacks = [lgb.log_evaluation(100), lgb.early_stopping(50)]
    model = lgb.train(
        params,
        dtrain,
        num_boost_round=1000,
        valid_sets=[dtrain, dval],
        valid_names=["train", "val"],
        callbacks=callbacks,
    )

    log.info("Best iteration: %d", model.best_iteration)

    # Evaluate on all splits
    results = {}
    for split_name, X, y in [("train", X_train, y_train),
                              ("validate", X_val, y_val),
                              ("test", X_test, y_test)]:
        preds = model.predict(X, num_iteration=model.best_iteration)
        # Clamp predictions to non-negative (snowfall can't be negative)
        preds = np.clip(preds, 0, None)
        mae = mean_absolute_error(y, preds)
        rmse = np.sqrt(mean_squared_error(y, preds))
        results[split_name] = {
            "mae": round(float(mae), 3),
            "rmse": round(float(rmse), 3),
            "n": int(len(y)),
        }
        log.info("%s — MAE: %.3f, RMSE: %.3f (n=%d)", split_name, mae, rmse, len(y))

    # Feature importance
    importance = pd.DataFrame({
        "feature": feature_cols,
        "importance": model.feature_importance(importance_type="gain"),
    }).sort_values("importance", ascending=False)

    log.info("\nTop 15 features by gain:")
    for _, row in importance.head(15).iterrows():
        log.info("  %s: %.1f", row["feature"], row["importance"])

    return {
        "model": model,
        "results": results,
        "feature_importance": importance,
        "feature_cols": feature_cols,
        "best_iteration": model.best_iteration,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    db = SessionLocal()
    try:
        log.info("Loading data from database...")
        labels, forecasts, obs = load_all_data(db)
        log.info("Labels: %d, Forecasts: %d, Observations: %d",
                 len(labels), len(forecasts), len(obs))
    finally:
        db.close()

    log.info("Building feature matrix...")
    df = build_feature_matrix(labels, forecasts, obs)

    log.info("Training model...")
    output = train_and_evaluate(df)

    # Save model
    MODEL_DIR.mkdir(exist_ok=True)
    model_path = MODEL_DIR / "snowfall_24h_alpine.pkl"
    with open(model_path, "wb") as f:
        pickle.dump({
            "model": output["model"],
            "feature_cols": output["feature_cols"],
            "target": TARGET_COL,
            "location": "alpine",
            "best_iteration": output["best_iteration"],
            "trained_at": datetime.now(timezone.utc).isoformat(),
        }, f)
    log.info("Model saved to %s", model_path)

    # Save evaluation report
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": "24h_snowfall_cm_alpine",
        "model": "lightgbm",
        "best_iteration": output["best_iteration"],
        "splits": output["results"],
        "baselines": {
            "raw_gfs": {"mae": 1.742, "rmse": 4.377},
            "persistence": {"mae": 2.419, "rmse": 5.394},
            "climatology": {"mae": 2.182, "rmse": 4.484},
        },
        "improvement_over_gfs": {
            "mae_reduction": round(1.742 - output["results"]["test"]["mae"], 3),
            "mae_pct": round((1 - output["results"]["test"]["mae"] / 1.742) * 100, 1),
        },
        "top_features": output["feature_importance"].head(20).to_dict("records"),
    }

    report_path = Path(__file__).parent.parent / "snowfall_model_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    log.info("Report saved to %s", report_path)

    # Print summary
    print("\n" + "=" * 60)
    print("24H ALPINE SNOWFALL MODEL — RESULTS")
    print("=" * 60)
    print(f"\nTest period: {TEST_START} to {TEST_END}")
    print(f"Best iteration: {output['best_iteration']}")
    print(f"\n{'Split':<12} {'MAE':>8} {'RMSE':>8} {'N':>8}")
    print("-" * 40)
    for split, vals in output["results"].items():
        print(f"{split:<12} {vals['mae']:>8.3f} {vals['rmse']:>8.3f} {vals['n']:>8}")

    print(f"\n{'Baseline':<15} {'MAE':>8} {'RMSE':>8}")
    print("-" * 35)
    print(f"{'Raw GFS':<15} {'1.742':>8} {'4.377':>8}")
    print(f"{'Persistence':<15} {'2.419':>8} {'5.394':>8}")
    print(f"{'Climatology':<15} {'2.182':>8} {'4.484':>8}")

    test_mae = output["results"]["test"]["mae"]
    improvement = 1.742 - test_mae
    pct = (1 - test_mae / 1.742) * 100
    if improvement > 0:
        print(f"\n✓ BEATS raw GFS by {improvement:.3f} MAE ({pct:.1f}% improvement)")
    else:
        print(f"\n✗ Does NOT beat raw GFS (difference: {improvement:.3f} MAE)")

    print("\nTop 10 features:")
    for _, row in output["feature_importance"].head(10).iterrows():
        print(f"  {row['feature']:<35} {row['importance']:.0f}")
    print("=" * 60)


if __name__ == "__main__":
    main()

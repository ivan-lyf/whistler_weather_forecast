"""Evaluate baseline forecast models against training labels."""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, mean_squared_error
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal

log = logging.getLogger("evaluate_baselines")

TRAIN_END = "2024-12-31"
VALIDATE_END = "2025-06-30"
TEST_START = "2025-07-01"
TEST_END = "2025-12-31"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_labels(db) -> pd.DataFrame:
    rows = db.execute(text("""
        SELECT tl.location_id, l.name as location_name, tl.target_time,
               tl.label_24h_snowfall_cm, tl.label_6h_wind_kmh,
               tl.label_12h_wind_kmh, tl.label_freezing_level_m,
               tl.label_precip_type
        FROM training_labels tl
        JOIN locations l ON l.id = tl.location_id
        ORDER BY tl.location_id, tl.target_time
    """)).all()
    df = pd.DataFrame(rows, columns=[
        "location_id", "location_name", "target_time",
        "label_24h_snowfall_cm", "label_6h_wind_kmh",
        "label_12h_wind_kmh", "label_freezing_level_m", "label_precip_type",
    ])
    df["target_time"] = pd.to_datetime(df["target_time"], utc=True)
    return df


def load_forecasts(db) -> pd.DataFrame:
    rows = db.execute(text("""
        SELECT fv.location_id, fv.valid_at, fv.lead_hours,
               fv.temperature_c, fv.precip_mm, fv.snowfall_cm,
               fv.wind_speed_kmh, fv.wind_gust_kmh,
               fv.freezing_level_m, fv.weather_code
        FROM forecast_values fv
        JOIN forecast_runs fr ON fr.id = fv.forecast_run_id
        WHERE fr.provider = 'open_meteo'
        ORDER BY fv.location_id, fv.valid_at
    """)).all()
    df = pd.DataFrame(rows, columns=[
        "location_id", "valid_at", "lead_hours",
        "temperature_c", "precip_mm", "snowfall_cm",
        "wind_speed_kmh", "wind_gust_kmh",
        "freezing_level_m", "weather_code",
    ])
    df["valid_at"] = pd.to_datetime(df["valid_at"], utc=True)
    return df


def load_observations(db) -> pd.DataFrame:
    rows = db.execute(text("""
        SELECT s.external_station_id, o.observed_at,
               o.snowfall_cm, o.wind_speed_kmh, o.wind_gust_kmh,
               o.temperature_c, o.precip_mm, s.elevation_m
        FROM obs_hourly o
        JOIN stations s ON s.id = o.station_id
        WHERE s.source = 'open_meteo'
        ORDER BY s.external_station_id, o.observed_at
    """)).all()
    df = pd.DataFrame(rows, columns=[
        "station_id", "observed_at", "snowfall_cm",
        "wind_speed_kmh", "wind_gust_kmh",
        "temperature_c", "precip_mm", "elevation_m",
    ])
    df["observed_at"] = pd.to_datetime(df["observed_at"], utc=True)
    # Map station to location_id
    station_to_loc = {"whistler_base": 1, "whistler_mid": 2, "whistler_alpine": 3}
    df["location_id"] = df["station_id"].map(station_to_loc)
    return df


# ---------------------------------------------------------------------------
# Baseline: Raw GFS forecast
# ---------------------------------------------------------------------------


def build_raw_gfs_predictions(forecasts: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Build GFS baseline predictions aligned with labels."""
    # For each (location, valid_at), compute rolling aggregates from hourly forecasts
    results = []

    for loc_id in labels["location_id"].unique():
        fc = forecasts[forecasts["location_id"] == loc_id].copy()
        lb = labels[labels["location_id"] == loc_id].copy()

        if fc.empty:
            continue

        fc = fc.sort_values("valid_at").set_index("valid_at")
        # Ensure hourly
        full_idx = pd.date_range(fc.index.min(), fc.index.max(), freq="h", tz="UTC")
        fc = fc.reindex(full_idx)

        # 24h snowfall from forecast
        pred_24h_snow = fc["snowfall_cm"].rolling(24, min_periods=20).sum()

        # Wind
        wind = fc["wind_gust_kmh"].fillna(fc["wind_speed_kmh"])
        pred_6h_wind = wind.rolling(6, min_periods=5).max()
        pred_12h_wind = wind.rolling(12, min_periods=10).max()

        # Freezing level (direct)
        pred_fzl = fc["freezing_level_m"]

        # Precip type from forecast
        temp = fc["temperature_c"]
        precip = fc["precip_mm"]
        has_precip = precip > 0.1
        pred_precip = pd.Series(None, index=fc.index, dtype=object)
        pred_precip[has_precip & (temp < 0)] = "snow"
        pred_precip[has_precip & (temp > 2)] = "rain"
        pred_precip[has_precip & (temp >= 0) & (temp <= 2)] = "mixed"

        preds = pd.DataFrame({
            "pred_24h_snowfall_cm": pred_24h_snow,
            "pred_6h_wind_kmh": pred_6h_wind,
            "pred_12h_wind_kmh": pred_12h_wind,
            "pred_freezing_level_m": pred_fzl,
            "pred_precip_type": pred_precip,
        }, index=fc.index)
        preds["location_id"] = loc_id
        preds = preds.reset_index().rename(columns={"index": "target_time"})

        # Merge with labels on target_time
        merged = lb.merge(preds, on=["location_id", "target_time"], how="inner")
        results.append(merged)

    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


# ---------------------------------------------------------------------------
# Baseline: Persistence
# ---------------------------------------------------------------------------


def build_persistence_predictions(obs: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Persistence baseline: yesterday's value predicts today's."""
    results = []

    for loc_id in labels["location_id"].unique():
        ob = obs[obs["location_id"] == loc_id].copy()
        lb = labels[labels["location_id"] == loc_id].copy()

        if ob.empty:
            continue

        ob = ob.sort_values("observed_at").set_index("observed_at")
        full_idx = pd.date_range(ob.index.min(), ob.index.max(), freq="h", tz="UTC")
        ob = ob.reindex(full_idx)

        # Persistence: shift the label-equivalent computations by 24h
        wind = ob["wind_gust_kmh"].fillna(ob["wind_speed_kmh"])
        snow_24h = ob["snowfall_cm"].rolling(24, min_periods=20).sum()
        wind_6h = wind.rolling(6, min_periods=5).max()
        wind_12h = wind.rolling(12, min_periods=10).max()

        preds = pd.DataFrame({
            "pred_24h_snowfall_cm": snow_24h.shift(24),   # yesterday's 24h total
            "pred_6h_wind_kmh": wind_6h.shift(6),         # 6h ago wind
            "pred_12h_wind_kmh": wind_12h.shift(12),      # 12h ago wind
            "pred_freezing_level_m": np.nan,               # no persistence for freezing level
        }, index=ob.index)

        # Precip type: carry forward last non-null within 6h
        temp = ob["temperature_c"]
        precip = ob["precip_mm"]
        has_precip = precip > 0.1
        obs_precip = pd.Series(None, index=ob.index, dtype=object)
        obs_precip[has_precip & (temp < 0)] = "snow"
        obs_precip[has_precip & (temp > 2)] = "rain"
        obs_precip[has_precip & (temp >= 0) & (temp <= 2)] = "mixed"
        preds["pred_precip_type"] = obs_precip.shift(1).ffill(limit=6)

        preds["location_id"] = loc_id
        preds = preds.reset_index().rename(columns={"index": "target_time"})

        merged = lb.merge(preds, on=["location_id", "target_time"], how="inner")
        results.append(merged)

    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


# ---------------------------------------------------------------------------
# Baseline: Climatology
# ---------------------------------------------------------------------------


def build_climatology_predictions(labels: pd.DataFrame, train_labels: pd.DataFrame) -> pd.DataFrame:
    """Climatology: month+hour averages from training period."""
    train = train_labels.copy()
    train["month"] = train["target_time"].dt.month
    train["hour"] = train["target_time"].dt.hour

    # Compute averages per (location, month, hour) from training data
    clim = train.groupby(["location_id", "month", "hour"]).agg(
        clim_24h_snow=("label_24h_snowfall_cm", "mean"),
        clim_6h_wind=("label_6h_wind_kmh", "mean"),
        clim_12h_wind=("label_12h_wind_kmh", "mean"),
        clim_fzl=("label_freezing_level_m", "mean"),
    ).reset_index()

    # Mode of precip_type (most common)
    precip_mode = (
        train[train["label_precip_type"].notna()]
        .groupby(["location_id", "month", "hour"])["label_precip_type"]
        .agg(lambda x: x.mode().iloc[0] if len(x.mode()) > 0 else None)
        .reset_index()
        .rename(columns={"label_precip_type": "clim_precip_type"})
    )
    clim = clim.merge(precip_mode, on=["location_id", "month", "hour"], how="left")

    # Merge onto test labels
    test = labels.copy()
    test["month"] = test["target_time"].dt.month
    test["hour"] = test["target_time"].dt.hour

    merged = test.merge(clim, on=["location_id", "month", "hour"], how="left")
    merged = merged.rename(columns={
        "clim_24h_snow": "pred_24h_snowfall_cm",
        "clim_6h_wind": "pred_6h_wind_kmh",
        "clim_12h_wind": "pred_12h_wind_kmh",
        "clim_fzl": "pred_freezing_level_m",
        "clim_precip_type": "pred_precip_type",
    })
    return merged


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def evaluate_regression(actual: pd.Series, predicted: pd.Series) -> dict:
    mask = actual.notna() & predicted.notna()
    a, p = actual[mask], predicted[mask]
    if len(a) == 0:
        return {"mae": None, "rmse": None, "n": 0}
    return {
        "mae": round(float(mean_absolute_error(a, p)), 3),
        "rmse": round(float(np.sqrt(mean_squared_error(a, p))), 3),
        "n": int(len(a)),
    }


def evaluate_classification(actual: pd.Series, predicted: pd.Series) -> dict:
    mask = actual.notna() & predicted.notna()
    a, p = actual[mask], predicted[mask]
    if len(a) == 0:
        return {"accuracy": None, "n": 0}
    result = {
        "accuracy": round(float(accuracy_score(a, p)), 3),
        "n": int(len(a)),
    }
    for cls in ["snow", "rain", "mixed"]:
        f1 = f1_score(a, p, labels=[cls], average=None, zero_division=0)
        result[f"f1_{cls}"] = round(float(f1[0]), 3) if len(f1) > 0 else 0.0
    return result


def evaluate_baseline(df: pd.DataFrame, name: str) -> dict:
    test_mask = (df["target_time"] >= TEST_START) & (df["target_time"] <= TEST_END)
    test = df[test_mask]

    log.info("Evaluating %s on %d test rows", name, len(test))

    metrics = {}

    # Regression targets
    for target, pred_col, locations in [
        ("24h_snowfall_cm", "pred_24h_snowfall_cm", ["alpine", "mid", "base"]),
        ("6h_wind_kmh", "pred_6h_wind_kmh", ["alpine", "mid", "base"]),
        ("12h_wind_kmh", "pred_12h_wind_kmh", ["alpine", "mid", "base"]),
        ("freezing_level_m", "pred_freezing_level_m", ["base"]),
    ]:
        label_col = f"label_{target}"
        for loc in locations:
            loc_mask = test["location_name"] == loc
            subset = test[loc_mask]
            if pred_col not in subset.columns:
                continue
            result = evaluate_regression(subset[label_col], subset[pred_col])
            key = f"{target}_{loc}"
            metrics[key] = result

    # Classification: precip type
    if "pred_precip_type" in test.columns:
        for loc in ["alpine", "mid", "base"]:
            loc_mask = test["location_name"] == loc
            subset = test[loc_mask]
            result = evaluate_classification(subset["label_precip_type"], subset["pred_precip_type"])
            metrics[f"precip_type_{loc}"] = result

    return metrics


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
        log.info("Loading data...")
        labels = load_labels(db)
        forecasts = load_forecasts(db)
        obs = load_observations(db)
    finally:
        db.close()

    log.info("Labels: %d rows, Forecasts: %d rows, Observations: %d rows",
             len(labels), len(forecasts), len(obs))

    # Split labels
    train_labels = labels[labels["target_time"] <= TRAIN_END]
    test_labels = labels[(labels["target_time"] >= TEST_START) & (labels["target_time"] <= TEST_END)]
    log.info("Train labels: %d, Test labels: %d", len(train_labels), len(test_labels))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "train_period": {"start": "2022-01-01", "end": TRAIN_END},
        "test_period": {"start": TEST_START, "end": TEST_END},
        "baselines": {},
    }

    # 1. Raw GFS baseline
    log.info("Building Raw GFS baseline...")
    gfs_df = build_raw_gfs_predictions(forecasts, labels)
    report["baselines"]["raw_gfs"] = evaluate_baseline(gfs_df, "Raw GFS")

    # 2. Persistence baseline
    log.info("Building Persistence baseline...")
    persist_df = build_persistence_predictions(obs, labels)
    report["baselines"]["persistence"] = evaluate_baseline(persist_df, "Persistence")

    # 3. Climatology baseline
    log.info("Building Climatology baseline...")
    clim_df = build_climatology_predictions(labels, train_labels)
    report["baselines"]["climatology"] = evaluate_baseline(clim_df, "Climatology")

    # Save report
    report_path = Path(__file__).parent.parent / "baseline_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    log.info("Report saved to %s", report_path)

    # Print summary
    print("\n" + "=" * 70)
    print("BASELINE EVALUATION REPORT")
    print(f"Test period: {TEST_START} to {TEST_END}")
    print("=" * 70)

    for baseline_name, metrics in report["baselines"].items():
        print(f"\n--- {baseline_name.upper()} ---")
        for metric_key, vals in sorted(metrics.items()):
            if "n" in vals and vals["n"] == 0:
                print(f"  {metric_key}: no data")
                continue
            parts = []
            for k, v in vals.items():
                if v is not None:
                    parts.append(f"{k}={v}")
            print(f"  {metric_key}: {', '.join(parts)}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()

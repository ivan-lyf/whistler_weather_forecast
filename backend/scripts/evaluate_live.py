"""Evaluate live predictions against observations.

Compares stored model_predictions (from past hours/days) against
now-available observations to compute rolling performance metrics.

Usage:
    python scripts/evaluate_live.py [--days 7] [--verbose]
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, mean_absolute_error, mean_squared_error
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models.evaluation_metric import EvaluationMetric

log = logging.getLogger("evaluate_live")

LOC_STATION_MAP = {1: "whistler_base", 2: "whistler_mid", 3: "whistler_alpine"}
LOC_NAMES = {1: "base", 2: "mid", 3: "alpine"}

HORIZON_BUCKETS = [
    ("0-6h", 0, 6),
    ("6-12h", 6, 12),
    ("12-24h", 12, 24),
    ("24-48h", 24, 48),
    ("all", 0, 999),
]

REGRESSION_TARGETS = ["snowfall_24h", "wind_6h", "wind_12h", "freezing_level"]
CLASSIFICATION_TARGETS = ["precip_type"]

# Test-period baselines (from Week 5-6 reports)
BASELINES = {
    "snowfall_24h": {"mae": 1.742},
    "wind_6h": {"mae": 8.229},
    "wind_12h": {"mae": 9.1},
    "freezing_level": {"mae": 379.192},
    "precip_type": {"accuracy": 0.875},
}

DRIFT_THRESHOLD = 1.5


def load_predictions(db, start: datetime, end: datetime) -> pd.DataFrame:
    rows = db.execute(text("""
        SELECT mp.location_id, mp.target_time, mp.target_name,
               mp.predicted_value, mp.predicted_class, mp.confidence,
               mp.forecast_run_id, fr.run_at
        FROM model_predictions mp
        JOIN forecast_runs fr ON fr.id = mp.forecast_run_id
        WHERE mp.target_time >= :start AND mp.target_time <= :end
        ORDER BY mp.target_name, mp.location_id, mp.target_time
    """), {"start": start, "end": end}).all()

    df = pd.DataFrame(rows, columns=[
        "location_id", "target_time", "target_name",
        "predicted_value", "predicted_class", "confidence",
        "forecast_run_id", "run_at",
    ])
    if not df.empty:
        df["target_time"] = pd.to_datetime(df["target_time"], utc=True)
        df["run_at"] = pd.to_datetime(df["run_at"], utc=True)
        df["lead_hours"] = ((df["target_time"] - df["run_at"]).dt.total_seconds() / 3600).astype(int)
    return df


def load_observations(db, start: datetime, end: datetime) -> pd.DataFrame:
    rows = db.execute(text("""
        SELECT s.external_station_id, o.observed_at,
               o.temperature_c, o.precip_mm, o.snowfall_cm,
               o.wind_speed_kmh, o.wind_gust_kmh
        FROM obs_hourly o
        JOIN stations s ON s.id = o.station_id
        WHERE s.source = 'open_meteo'
          AND o.observed_at >= :start AND o.observed_at <= :end
        ORDER BY s.external_station_id, o.observed_at
    """), {"start": start, "end": end}).all()

    df = pd.DataFrame(rows, columns=[
        "station_id", "observed_at", "temperature_c", "precip_mm",
        "snowfall_cm", "wind_speed_kmh", "wind_gust_kmh",
    ])
    if not df.empty:
        df["observed_at"] = pd.to_datetime(df["observed_at"], utc=True)
        station_to_loc = {"whistler_base": 1, "whistler_mid": 2, "whistler_alpine": 3}
        df["location_id"] = df["station_id"].map(station_to_loc)
    return df


def compute_obs_labels(obs: pd.DataFrame) -> pd.DataFrame:
    """Compute rolling observation-based labels to compare against predictions."""
    results = []
    for loc_id in obs["location_id"].dropna().unique():
        loc_obs = obs[obs["location_id"] == loc_id].copy()
        loc_obs = loc_obs.sort_values("observed_at").set_index("observed_at")
        idx = pd.date_range(loc_obs.index.min(), loc_obs.index.max(), freq="h", tz="UTC")
        loc_obs = loc_obs.reindex(idx)

        snow_24h = loc_obs["snowfall_cm"].rolling(24, min_periods=20).sum()
        wind = loc_obs["wind_gust_kmh"].fillna(loc_obs["wind_speed_kmh"])
        wind_6h = wind.rolling(6, min_periods=5).max()
        wind_12h = wind.rolling(12, min_periods=10).max()

        # Precip type
        temp = loc_obs["temperature_c"]
        precip = loc_obs["precip_mm"]
        has_precip = precip > 0.1
        precip_type = pd.Series(None, index=idx, dtype=object)
        precip_type[has_precip & (temp < 0)] = "snow"
        precip_type[has_precip & (temp > 2)] = "rain"
        precip_type[has_precip & (temp >= 0) & (temp <= 2)] = "mixed"

        labels = pd.DataFrame({
            "location_id": int(loc_id),
            "observed_at": idx,
            "obs_snowfall_24h": snow_24h.values,
            "obs_wind_6h": wind_6h.values,
            "obs_wind_12h": wind_12h.values,
            "obs_precip_type": precip_type.values,
        })
        results.append(labels)

    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


TARGET_OBS_MAP = {
    "snowfall_24h": "obs_snowfall_24h",
    "wind_6h": "obs_wind_6h",
    "wind_12h": "obs_wind_12h",
}


def evaluate(preds: pd.DataFrame, obs_labels: pd.DataFrame) -> list[dict]:
    """Compute metrics for each (target, location, horizon_bucket)."""
    now = datetime.now(timezone.utc)
    metrics = []

    for target in REGRESSION_TARGETS:
        target_preds = preds[preds["target_name"] == target]
        if target_preds.empty:
            continue

        obs_col = TARGET_OBS_MAP.get(target)

        for loc_id in target_preds["location_id"].unique():
            loc_preds = target_preds[target_preds["location_id"] == loc_id]

            if target == "freezing_level":
                # Freezing level: compare against label from training_labels if available
                # For now skip if no observation proxy exists
                continue

            if obs_col is None:
                continue

            # Merge predictions with observation labels
            merged = loc_preds.merge(
                obs_labels[obs_labels["location_id"] == loc_id][["observed_at", obs_col]],
                left_on="target_time", right_on="observed_at", how="inner",
            )

            if merged.empty:
                continue

            for bucket_name, h_min, h_max in HORIZON_BUCKETS:
                bucket = merged[(merged["lead_hours"] >= h_min) & (merged["lead_hours"] < h_max)]
                valid = bucket.dropna(subset=["predicted_value", obs_col])
                if len(valid) < 3:
                    continue

                mae = mean_absolute_error(valid[obs_col], valid["predicted_value"])
                rmse = np.sqrt(mean_squared_error(valid[obs_col], valid["predicted_value"]))

                metrics.append({
                    "model_version": "v1",
                    "evaluated_at": now,
                    "target_name": target,
                    "horizon_hours": h_max if bucket_name != "all" else None,
                    "location_id": int(loc_id),
                    "mae": round(float(mae), 3),
                    "rmse": round(float(rmse), 3),
                    "accuracy": None,
                    "n_samples": int(len(valid)),
                })

    # Classification: precip_type
    for target in CLASSIFICATION_TARGETS:
        target_preds = preds[preds["target_name"] == target]
        if target_preds.empty:
            continue

        for loc_id in target_preds["location_id"].unique():
            loc_preds = target_preds[target_preds["location_id"] == loc_id]

            merged = loc_preds.merge(
                obs_labels[obs_labels["location_id"] == loc_id][["observed_at", "obs_precip_type"]],
                left_on="target_time", right_on="observed_at", how="inner",
            )

            valid = merged.dropna(subset=["predicted_class", "obs_precip_type"])
            if len(valid) < 3:
                continue

            acc = accuracy_score(valid["obs_precip_type"], valid["predicted_class"])
            metrics.append({
                "model_version": "v1",
                "evaluated_at": now,
                "target_name": target,
                "horizon_hours": None,
                "location_id": int(loc_id),
                "mae": None,
                "rmse": None,
                "accuracy": round(float(acc), 3),
                "n_samples": int(len(valid)),
            })

    return metrics


def check_drift(metrics: list[dict]) -> list[dict]:
    """Check if any target's rolling MAE exceeds drift threshold."""
    alerts = []
    for m in metrics:
        if m["horizon_hours"] is not None:
            continue  # only check "all" bucket
        target = m["target_name"]
        baseline = BASELINES.get(target, {})

        if m["mae"] is not None and "mae" in baseline:
            ratio = m["mae"] / baseline["mae"]
            if ratio > DRIFT_THRESHOLD:
                alerts.append({
                    "target": target,
                    "location": LOC_NAMES.get(m["location_id"], "unknown"),
                    "rolling_mae": m["mae"],
                    "baseline_mae": baseline["mae"],
                    "ratio": round(ratio, 2),
                })
                log.warning("DRIFT DETECTED: %s %s — MAE %.3f vs baseline %.3f (%.1fx)",
                            target, LOC_NAMES.get(m["location_id"]), m["mae"], baseline["mae"], ratio)

        if m["accuracy"] is not None and "accuracy" in baseline:
            if m["accuracy"] < baseline["accuracy"] * 0.8:
                alerts.append({
                    "target": target,
                    "location": LOC_NAMES.get(m["location_id"], "unknown"),
                    "rolling_accuracy": m["accuracy"],
                    "baseline_accuracy": baseline["accuracy"],
                })
                log.warning("DRIFT DETECTED: %s — accuracy %.3f vs baseline %.3f",
                            target, m["accuracy"], baseline["accuracy"])

    return alerts


def main():
    parser = argparse.ArgumentParser(description="Evaluate live predictions")
    parser.add_argument("--days", type=int, default=7, help="Evaluate predictions from last N days")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=args.days)
    end = now
    log.info("Evaluating predictions from %s to %s", start.date(), end.date())

    db = SessionLocal()
    try:
        preds = load_predictions(db, start, end)
        log.info("Loaded %d predictions", len(preds))

        if preds.empty:
            log.info("No predictions to evaluate yet. Run the pipeline first.")
            return

        obs = load_observations(db, start - timedelta(hours=48), end)
        log.info("Loaded %d observations", len(obs))

        if obs.empty:
            log.info("No observations available for evaluation window.")
            return

        obs_labels = compute_obs_labels(obs)
        log.info("Computed %d observation labels", len(obs_labels))

        metrics = evaluate(preds, obs_labels)
        log.info("Computed %d metric entries", len(metrics))

        if metrics:
            # Clear old metrics for this evaluation window
            db.execute(text(
                "DELETE FROM evaluation_metrics WHERE evaluated_at >= :start"
            ), {"start": start})
            db.commit()

            db.execute(pg_insert(EvaluationMetric.__table__).values(metrics))
            db.commit()
            log.info("Stored %d evaluation metrics", len(metrics))

            # Check drift
            alerts = check_drift(metrics)
            if alerts:
                log.warning("Drift alerts: %s", json.dumps(alerts, indent=2))
            else:
                log.info("No drift detected — all models within baseline thresholds")

            # Print summary
            for m in metrics:
                if m["horizon_hours"] is None:
                    loc = LOC_NAMES.get(m["location_id"], "?")
                    if m["mae"] is not None:
                        log.info("  %s/%s: MAE=%.3f RMSE=%.3f (n=%d)",
                                 m["target_name"], loc, m["mae"], m["rmse"], m["n_samples"])
                    elif m["accuracy"] is not None:
                        log.info("  %s/%s: accuracy=%.3f (n=%d)",
                                 m["target_name"], loc, m["accuracy"], m["n_samples"])
        else:
            log.info("No metrics computed — predictions may not overlap with observations yet.")

    finally:
        db.close()

    log.info("Done.")


if __name__ == "__main__":
    main()

"""Generate predictions from the latest forecast run and store in model_predictions table.

Run after ingest_live_forecast.py to pre-compute predictions for the dashboard.

Usage:
    python scripts/generate_predictions.py [--hours 168] [--verbose]
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models.forecast import ForecastRun
from app.models.model_prediction import ModelPrediction
from app.prediction import (
    LOC_NAMES,
    LOC_STATION_MAP,
    PRECIP_CLASS_INV,
    _build_features_inline,
    _load_forecast_data,
    _load_model,
    _load_obs_data,
)

log = logging.getLogger("generate_predictions")

MODEL_VERSION = "v1"
REGRESSION_MODELS = [
    ("snowfall_24h_alpine", "snowfall_24h", "cm"),
    ("wind_6h_alpine", "wind_6h", "km/h"),
    ("wind_12h_alpine", "wind_12h", "km/h"),
]
CLASSIFICATION_MODELS = [
    ("precip_type_alpine", "precip_type"),
]
FREEZING_MODEL = ("freezing_level_base", "freezing_level", "m")


def get_latest_live_run(db) -> ForecastRun | None:
    return db.execute(
        select(ForecastRun)
        .where(ForecastRun.provider == "open_meteo", ForecastRun.model_name == "gfs_live")
        .order_by(ForecastRun.run_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def generate_for_location(db, loc_id: int, run: ForecastRun,
                          fc_base, obs_base, hours: int) -> list[dict]:
    loc_name = LOC_NAMES[loc_id]
    station_id = LOC_STATION_MAP[loc_id]
    now = datetime.now(timezone.utc)

    start = run.run_at
    end = run.run_at + timedelta(hours=hours)
    buf_start = start - timedelta(hours=48)

    fc = _load_forecast_data(db, loc_id, buf_start, end)
    obs = _load_obs_data(db, station_id, buf_start, end)

    if fc.empty:
        log.warning("No forecast data for %s", loc_name)
        return []

    fc_base_ref = fc_base if loc_id != 1 else None
    features = _build_features_inline(fc, obs, fc_base_ref)

    idx = features.loc[start:end].index
    if len(idx) == 0:
        return []

    rows = []

    # Temperature (raw forecast, no ML model)
    try:
        fc_sorted = fc.sort_values("valid_at").set_index("valid_at").reindex(idx)
        for t in idx:
            temp = fc_sorted.loc[t, "temperature_c"] if t in fc_sorted.index else None
            if temp is not None and not pd.isna(temp):
                rows.append({
                    "model_version": MODEL_VERSION,
                    "generated_at": now,
                    "location_id": loc_id,
                    "target_time": t.to_pydatetime(),
                    "target_name": "temperature",
                    "predicted_value": round(float(temp), 1),
                    "predicted_class": None,
                    "confidence": None,
                    "forecast_run_id": run.id,
                })
    except Exception as e:
        log.warning("Temperature extraction failed for %s: %s", loc_name, e)

    # Regression models
    for model_name, target_name, unit in REGRESSION_MODELS:
        try:
            m = _load_model(model_name)
            X = features.loc[idx, m["feature_cols"]]
            preds = np.clip(m["model"].predict(X, num_iteration=m["best_iteration"]), 0, None)
            for t, v in zip(idx, preds):
                rows.append({
                    "model_version": MODEL_VERSION,
                    "generated_at": now,
                    "location_id": loc_id,
                    "target_time": t.to_pydatetime(),
                    "target_name": target_name,
                    "predicted_value": round(float(v), 2),
                    "predicted_class": None,
                    "confidence": None,
                    "forecast_run_id": run.id,
                })
        except Exception as e:
            log.warning("%s prediction failed for %s: %s", target_name, loc_name, e)

    # Freezing level (uses base features)
    try:
        m = _load_model(FREEZING_MODEL[0])
        features_base = _build_features_inline(fc_base, obs_base)
        X = features_base.loc[idx, m["feature_cols"]]
        preds = np.clip(m["model"].predict(X, num_iteration=m["best_iteration"]), 0, 5000)
        for t, v in zip(idx, preds):
            rows.append({
                "model_version": MODEL_VERSION,
                "generated_at": now,
                "location_id": loc_id,
                "target_time": t.to_pydatetime(),
                "target_name": "freezing_level",
                "predicted_value": round(float(v), 0),
                "predicted_class": None,
                "confidence": None,
                "forecast_run_id": run.id,
            })
    except Exception as e:
        log.warning("freezing_level prediction failed for %s: %s", loc_name, e)

    # Classification
    for model_name, target_name in CLASSIFICATION_MODELS:
        try:
            m = _load_model(model_name)
            X = features.loc[idx, m["feature_cols"]]
            raw_preds = m["model"].predict(X, num_iteration=m["best_iteration"])
            pred_classes = raw_preds.argmax(axis=1)
            confidences = raw_preds.max(axis=1)
            for t, cls, conf in zip(idx, pred_classes, confidences):
                rows.append({
                    "model_version": MODEL_VERSION,
                    "generated_at": now,
                    "location_id": loc_id,
                    "target_time": t.to_pydatetime(),
                    "target_name": target_name,
                    "predicted_value": None,
                    "predicted_class": PRECIP_CLASS_INV[cls],
                    "confidence": round(float(conf), 3),
                    "forecast_run_id": run.id,
                })
        except Exception as e:
            log.warning("%s prediction failed for %s: %s", target_name, loc_name, e)

    return rows


def main():
    parser = argparse.ArgumentParser(description="Generate and store predictions")
    parser.add_argument("--hours", type=int, default=168, help="Hours ahead to predict (default: 168 = 7 days)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    db = SessionLocal()
    try:
        run = get_latest_live_run(db)
        if not run:
            log.error("No live forecast run found. Run ingest_live_forecast.py first.")
            sys.exit(1)

        log.info("Using forecast run: %s (run_at=%s)", run.id, run.run_at)

        buf_start = run.run_at - timedelta(hours=48)
        end = run.run_at + timedelta(hours=args.hours)
        fc_base = _load_forecast_data(db, 1, buf_start, end)
        obs_base = _load_obs_data(db, "whistler_base", buf_start, end)

        all_rows = []
        for loc_id in [1, 2, 3]:
            loc_name = LOC_NAMES[loc_id]
            log.info("Generating predictions for %s...", loc_name)
            rows = generate_for_location(db, loc_id, run, fc_base, obs_base, args.hours)
            all_rows.extend(rows)
            log.info("  %s: %d prediction rows", loc_name, len(rows))

        if all_rows:
            # Atomic replace: delete old + insert new in one transaction
            try:
                db.execute(text(
                    "DELETE FROM model_predictions WHERE forecast_run_id = :rid"
                ), {"rid": run.id})

                batch_size = 1000
                for i in range(0, len(all_rows), batch_size):
                    db.execute(pg_insert(ModelPrediction.__table__).values(all_rows[i:i + batch_size]))

                db.commit()
                log.info("Stored %d predictions total", len(all_rows))
            except Exception:
                db.rollback()
                log.exception("Failed to store predictions — rolled back")
                sys.exit(1)
        else:
            log.warning("No predictions generated")

    finally:
        db.close()

    log.info("Done.")


if __name__ == "__main__":
    main()

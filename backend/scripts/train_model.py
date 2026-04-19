"""General model training script for all forecast correction targets.

Usage:
    python scripts/train_model.py --target wind_6h
    python scripts/train_model.py --target wind_12h
    python scripts/train_model.py --target freezing_level
    python scripts/train_model.py --target precip_type
    python scripts/train_model.py --target snowfall_24h
"""

import argparse
import json
import logging
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, mean_squared_error
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from scripts.features import (
    build_cross_elevation_features,
    build_ensemble_features,
    build_forecast_features,
    build_observation_features,
    build_temporal_features,
    simulate_missing_obs,
)

log = logging.getLogger("train_model")

# Defaults — overridable via CLI
DEFAULT_TRAIN_END = "2024-12-31"
DEFAULT_VALIDATE_START = "2025-01-01"
DEFAULT_VALIDATE_END = "2025-06-30"
DEFAULT_TEST_START = "2025-07-01"
DEFAULT_TEST_END = "2025-12-31"

MODEL_DIR = Path(__file__).parent.parent / "models"

PRECIP_CLASSES = ["snow", "rain", "mixed", "none"]
PRECIP_CLASS_MAP = {c: i for i, c in enumerate(PRECIP_CLASSES)}
PRECIP_CLASS_INV = {i: c for c, i in PRECIP_CLASS_MAP.items()}

TARGETS = {
    "snowfall_24h": {
        "label_col": "label_24h_snowfall_cm",
        "task": "regression",
        "location_id": 3,
        "location_name": "alpine",
        "clamp_min": 0,
        "baselines": {
            "raw_gfs": {"mae": 1.742, "rmse": 4.377},
            "persistence": {"mae": 2.419, "rmse": 5.394},
            "climatology": {"mae": 2.182, "rmse": 4.484},
        },
    },
    "wind_6h": {
        "label_col": "label_6h_wind_kmh",
        "task": "regression",
        "location_id": 3,
        "location_name": "alpine",
        "clamp_min": 0,
        "baselines": {
            "raw_gfs": {"mae": 10.504, "rmse": 12.234},
            "persistence": {"mae": 8.229, "rmse": 10.729},
            "climatology": {"mae": 8.757, "rmse": 11.481},
        },
    },
    "wind_12h": {
        "label_col": "label_12h_wind_kmh",
        "task": "regression",
        "location_id": 3,
        "location_name": "alpine",
        "clamp_min": 0,
        "baselines": {
            "raw_gfs": {"mae": 11.307, "rmse": 12.869},
            "persistence": {"mae": 9.223, "rmse": 12.002},
            "climatology": {"mae": 9.1, "rmse": 11.817},
        },
    },
    "freezing_level": {
        "label_col": "label_freezing_level_m",
        "task": "regression",
        "location_id": 1,
        "location_name": "base",
        "clamp_min": 0,
        "baselines": {
            "raw_gfs": {"mae": 514.12, "rmse": 799.999},
            "climatology": {"mae": 379.192, "rmse": 468.421},
        },
    },
    "precip_type": {
        "label_col": "label_precip_type",
        "task": "classification",
        "location_id": 3,
        "location_name": "alpine",
        "baselines": {
            "raw_gfs": {"accuracy": 0.875},
            "persistence": {"accuracy": 0.938},
            "climatology": {"accuracy": 0.591},
        },
    },
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_forecasts_by_model(db, model_name: str) -> pd.DataFrame:
    df = pd.DataFrame(
        db.execute(text("""
            SELECT fv.location_id, fv.valid_at, fv.lead_hours,
                   fv.temperature_c, fv.precip_mm, fv.snowfall_cm,
                   fv.wind_speed_kmh, fv.wind_gust_kmh, fv.humidity_pct,
                   fv.pressure_hpa, fv.freezing_level_m, fv.weather_code
            FROM forecast_values fv
            JOIN forecast_runs fr ON fr.id = fv.forecast_run_id
            WHERE fr.provider = 'open_meteo' AND fr.model_name = :model
            ORDER BY fv.location_id, fv.valid_at
        """), {"model": model_name}).all(),
        columns=["location_id", "valid_at", "lead_hours",
                 "temperature_c", "precip_mm", "snowfall_cm",
                 "wind_speed_kmh", "wind_gust_kmh", "humidity_pct",
                 "pressure_hpa", "freezing_level_m", "weather_code"],
    )
    if not df.empty:
        df["valid_at"] = pd.to_datetime(df["valid_at"], utc=True)
        df = df.drop_duplicates(subset=["location_id", "valid_at"], keep="last")
    return df


def load_all_data(db) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    labels = pd.DataFrame(
        db.execute(text("""
            SELECT tl.location_id, l.name as location_name, tl.target_time,
                   tl.label_24h_snowfall_cm, tl.label_6h_wind_kmh,
                   tl.label_12h_wind_kmh, tl.label_freezing_level_m,
                   tl.label_precip_type
            FROM training_labels tl
            JOIN locations l ON l.id = tl.location_id
            ORDER BY tl.location_id, tl.target_time
        """)).all(),
        columns=["location_id", "location_name", "target_time",
                 "label_24h_snowfall_cm", "label_6h_wind_kmh",
                 "label_12h_wind_kmh", "label_freezing_level_m",
                 "label_precip_type"],
    )
    labels["target_time"] = pd.to_datetime(labels["target_time"], utc=True)

    gfs_forecasts = _load_forecasts_by_model(db, "gfs_seamless")
    ecmwf_forecasts = _load_forecasts_by_model(db, "ecmwf_ifs025")
    log.info("Loaded GFS: %d rows, ECMWF: %d rows", len(gfs_forecasts), len(ecmwf_forecasts))

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
    obs["location_id"] = obs["station_id"].map(
        {"whistler_base": 1, "whistler_mid": 2, "whistler_alpine": 3}
    )

    return labels, gfs_forecasts, ecmwf_forecasts, obs


# ---------------------------------------------------------------------------
# Feature matrix
# ---------------------------------------------------------------------------


def build_feature_matrix(target_cfg: dict, labels: pd.DataFrame,
                         gfs_forecasts: pd.DataFrame, ecmwf_forecasts: pd.DataFrame,
                         obs: pd.DataFrame, train_end: str) -> pd.DataFrame:
    location_id = target_cfg["location_id"]
    label_col = target_cfg["label_col"]

    loc_labels = labels[labels["location_id"] == location_id].copy()
    loc_labels = loc_labels.set_index("target_time")

    log.info("Building GFS forecast features (location_id=%d)...", location_id)
    fc_features = build_forecast_features(gfs_forecasts, location_id)

    log.info("Building cross-elevation features...")
    cross_features = build_cross_elevation_features(gfs_forecasts)

    log.info("Building ensemble features (GFS vs ECMWF)...")
    ens_features = build_ensemble_features(gfs_forecasts, ecmwf_forecasts, location_id)

    log.info("Building observation features (location_id=%d)...", location_id)
    obs_features = build_observation_features(obs, location_id)

    log.info("Building temporal features...")
    temporal_features = build_temporal_features(loc_labels.index)

    df = loc_labels[[label_col]].copy()
    df = df.join(fc_features, how="left")
    df = df.join(cross_features, how="left")
    df = df.join(ens_features, how="left")
    df = df.join(obs_features, how="left")
    df = df.join(temporal_features, how="left")

    # Simulate missing observations in training data to match production conditions.
    train_mask = df.index <= train_end
    df_train_part = df[train_mask].copy()
    df_other_part = df[~train_mask]
    df_train_part = simulate_missing_obs(df_train_part, missing_rate=0.15, seed=42)
    df = pd.concat([df_train_part, df_other_part])
    log.info("Applied 15%% obs masking to %d training rows", train_mask.sum())

    # For classification, encode target as integer
    if target_cfg["task"] == "classification":
        df[label_col] = df[label_col].map(PRECIP_CLASS_MAP)

    df = df.dropna(subset=[label_col])

    log.info("Feature matrix: %d rows, %d feature columns", len(df), len(df.columns) - 1)
    return df


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def get_lgb_params(target_cfg: dict) -> dict:
    base_params = {
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

    if target_cfg["task"] == "regression":
        base_params["objective"] = "regression"
        base_params["metric"] = ["mae", "rmse"]
    else:
        base_params["objective"] = "multiclass"
        base_params["num_class"] = len(PRECIP_CLASSES)
        base_params["metric"] = ["multi_logloss"]

    return base_params


def train_and_evaluate(target_cfg: dict, df: pd.DataFrame,
                       train_end: str, val_start: str, val_end: str,
                       test_start: str, test_end: str) -> dict:
    label_col = target_cfg["label_col"]
    feature_cols = [c for c in df.columns if c != label_col]

    train = df[df.index <= train_end]
    validate = df[(df.index >= val_start) & (df.index <= val_end)]
    test = df[(df.index >= test_start) & (df.index <= test_end)]

    log.info("Split sizes — train: %d, validate: %d, test: %d",
             len(train), len(validate), len(test))

    X_train, y_train = train[feature_cols], train[label_col]
    X_val, y_val = validate[feature_cols], validate[label_col]
    X_test, y_test = test[feature_cols], test[label_col]

    params = get_lgb_params(target_cfg)

    dtrain = lgb.Dataset(X_train, label=y_train)
    dval = lgb.Dataset(X_val, label=y_val, reference=dtrain)

    log.info("Training LightGBM (%s)...", target_cfg["task"])
    model = lgb.train(
        params, dtrain,
        num_boost_round=1000,
        valid_sets=[dtrain, dval],
        valid_names=["train", "val"],
        callbacks=[lgb.log_evaluation(100), lgb.early_stopping(50)],
    )
    log.info("Best iteration: %d", model.best_iteration)

    # Evaluate
    results = {}
    for split_name, X, y in [("train", X_train, y_train),
                              ("validate", X_val, y_val),
                              ("test", X_test, y_test)]:
        raw_preds = model.predict(X, num_iteration=model.best_iteration)

        if target_cfg["task"] == "regression":
            preds = raw_preds
            if "clamp_min" in target_cfg:
                preds = np.clip(preds, target_cfg["clamp_min"], None)
            mae = mean_absolute_error(y, preds)
            rmse = np.sqrt(mean_squared_error(y, preds))
            results[split_name] = {
                "mae": round(float(mae), 3),
                "rmse": round(float(rmse), 3),
                "n": int(len(y)),
            }
            log.info("%s — MAE: %.3f, RMSE: %.3f (n=%d)", split_name, mae, rmse, len(y))
        else:
            # Multiclass: raw_preds is (n_samples, n_classes)
            pred_classes = raw_preds.argmax(axis=1)
            confidence = raw_preds.max(axis=1)

            acc = accuracy_score(y, pred_classes)
            f1s = {}
            for cls_name, cls_idx in PRECIP_CLASS_MAP.items():
                f1 = f1_score(y, pred_classes, labels=[cls_idx], average=None, zero_division=0)
                f1s[f"f1_{cls_name}"] = round(float(f1[0]), 3) if len(f1) > 0 else 0.0

            results[split_name] = {
                "accuracy": round(float(acc), 3),
                "mean_confidence": round(float(confidence.mean()), 3),
                "n": int(len(y)),
                **f1s,
            }
            log.info("%s — accuracy: %.3f, n=%d, f1: %s", split_name, acc, len(y), f1s)

    # Feature importance
    importance = pd.DataFrame({
        "feature": feature_cols,
        "importance": model.feature_importance(importance_type="gain"),
    }).sort_values("importance", ascending=False)

    log.info("\nTop 10 features:")
    for _, row in importance.head(10).iterrows():
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


def walk_forward_cv(df: pd.DataFrame, target_cfg: dict, n_splits: int = 5,
                    test_days: int = 90) -> list[dict]:
    """Walk-forward cross-validation for time series."""
    start_date = df.index.min()
    end_date = df.index.max()
    total_days = (end_date - start_date).days
    # Reserve last test_days*2 for final validation, split the rest
    usable_days = total_days - test_days
    step = usable_days // (n_splits + 1)

    all_results = []
    for i in range(n_splits):
        train_end = start_date + pd.Timedelta(days=step * (i + 1))
        val_start = train_end + pd.Timedelta(hours=1)
        val_end = train_end + pd.Timedelta(days=test_days // 2)
        test_start = val_end + pd.Timedelta(hours=1)
        test_end = val_end + pd.Timedelta(days=test_days // 2)

        log.info("CV fold %d/%d: train<=%.10s val=%.10s..%.10s test=%.10s..%.10s",
                 i + 1, n_splits, str(train_end), str(val_start), str(val_end),
                 str(test_start), str(test_end))

        output = train_and_evaluate(
            target_cfg, df,
            str(train_end), str(val_start), str(val_end),
            str(test_start), str(test_end),
        )
        all_results.append(output["results"]["test"])

    return all_results


def main():
    parser = argparse.ArgumentParser(description="Train a forecast correction model")
    parser.add_argument("--target", required=True, choices=list(TARGETS.keys()),
                        help="Target to train")
    parser.add_argument("--train-end", default=DEFAULT_TRAIN_END, help="Training cutoff (YYYY-MM-DD)")
    parser.add_argument("--val-start", default=DEFAULT_VALIDATE_START)
    parser.add_argument("--val-end", default=DEFAULT_VALIDATE_END)
    parser.add_argument("--test-start", default=DEFAULT_TEST_START)
    parser.add_argument("--test-end", default=DEFAULT_TEST_END)
    parser.add_argument("--cv", type=int, default=0, help="Walk-forward CV folds (0=disabled)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    target_cfg = TARGETS[args.target]
    log.info("Training target: %s (%s at %s)",
             args.target, target_cfg["task"], target_cfg["location_name"])

    db = SessionLocal()
    try:
        log.info("Loading data...")
        labels, gfs_forecasts, ecmwf_forecasts, obs = load_all_data(db)
        log.info("Labels: %d, GFS: %d, ECMWF: %d, Obs: %d",
                 len(labels), len(gfs_forecasts), len(ecmwf_forecasts), len(obs))
    finally:
        db.close()

    log.info("Building feature matrix...")
    df = build_feature_matrix(target_cfg, labels, gfs_forecasts, ecmwf_forecasts, obs, args.train_end)

    # Walk-forward CV mode
    if args.cv > 0:
        log.info("Running %d-fold walk-forward CV...", args.cv)
        cv_results = walk_forward_cv(df, target_cfg, n_splits=args.cv)
        print(f"\n{'=' * 60}")
        print(f"{args.target.upper()} — {args.cv}-FOLD WALK-FORWARD CV")
        print(f"{'=' * 60}")
        if target_cfg["task"] == "regression":
            maes = [r["mae"] for r in cv_results]
            print(f"Test MAE: {np.mean(maes):.3f} +/- {np.std(maes):.3f}")
            print(f"  Per fold: {[r['mae'] for r in cv_results]}")
        else:
            accs = [r["accuracy"] for r in cv_results]
            print(f"Test accuracy: {np.mean(accs):.3f} +/- {np.std(accs):.3f}")
            print(f"  Per fold: {[r['accuracy'] for r in cv_results]}")
        print(f"{'=' * 60}")
        return

    log.info("Training (train<=%s, val=%s..%s, test=%s..%s)...",
             args.train_end, args.val_start, args.val_end, args.test_start, args.test_end)
    output = train_and_evaluate(target_cfg, df,
                                args.train_end, args.val_start, args.val_end,
                                args.test_start, args.test_end)

    # Save model
    MODEL_DIR.mkdir(exist_ok=True)
    model_filename = f"{args.target}_{target_cfg['location_name']}.pkl"
    model_path = MODEL_DIR / model_filename
    with open(model_path, "wb") as f:
        pickle.dump({
            "model": output["model"],
            "feature_cols": output["feature_cols"],
            "target": args.target,
            "label_col": target_cfg["label_col"],
            "task": target_cfg["task"],
            "location": target_cfg["location_name"],
            "location_id": target_cfg["location_id"],
            "best_iteration": output["best_iteration"],
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "class_map": PRECIP_CLASS_MAP if target_cfg["task"] == "classification" else None,
        }, f)
    log.info("Model saved to %s", model_path)

    # Build report
    best_baseline_name = min(target_cfg["baselines"],
                             key=lambda k: target_cfg["baselines"][k].get("mae",
                                           target_cfg["baselines"][k].get("accuracy", 0) * -1))
    best_baseline = target_cfg["baselines"][best_baseline_name]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": args.target,
        "location": target_cfg["location_name"],
        "task": target_cfg["task"],
        "model": "lightgbm",
        "best_iteration": output["best_iteration"],
        "splits": output["results"],
        "baselines": target_cfg["baselines"],
        "top_features": output["feature_importance"].head(20).to_dict("records"),
    }

    report_path = Path(__file__).parent.parent / f"{args.target}_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    log.info("Report saved to %s", report_path)

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"{args.target.upper()} MODEL — RESULTS")
    print(f"{'=' * 60}")
    print(f"Location: {target_cfg['location_name']}, Task: {target_cfg['task']}")
    print(f"Best iteration: {output['best_iteration']}")

    if target_cfg["task"] == "regression":
        print(f"\n{'Split':<12} {'MAE':>8} {'RMSE':>8} {'N':>8}")
        print("-" * 40)
        for split, vals in output["results"].items():
            print(f"{split:<12} {vals['mae']:>8.3f} {vals['rmse']:>8.3f} {vals['n']:>8}")
        print(f"\n{'Baseline':<15} {'MAE':>8} {'RMSE':>8}")
        print("-" * 35)
        for name, vals in target_cfg["baselines"].items():
            print(f"{name:<15} {vals['mae']:>8.3f} {vals['rmse']:>8.3f}")
        test_mae = output["results"]["test"]["mae"]
        best_mae = best_baseline.get("mae", float("inf"))
        if test_mae < best_mae:
            pct = (1 - test_mae / best_mae) * 100
            print(f"\n>> BEATS best baseline ({best_baseline_name}) by {pct:.1f}%")
        else:
            print(f"\n>> Does NOT beat best baseline ({best_baseline_name}: {best_mae:.3f})")
    else:
        print(f"\n{'Split':<12} {'Acc':>8} {'Conf':>8} {'N':>8}")
        print("-" * 40)
        for split, vals in output["results"].items():
            print(f"{split:<12} {vals['accuracy']:>8.3f} {vals.get('mean_confidence', 0):>8.3f} {vals['n']:>8}")
        print(f"\n{'Baseline':<15} {'Acc':>8}")
        print("-" * 25)
        for name, vals in target_cfg["baselines"].items():
            print(f"{name:<15} {vals['accuracy']:>8.3f}")
        test_acc = output["results"]["test"]["accuracy"]
        for name, vals in target_cfg["baselines"].items():
            if test_acc > vals["accuracy"]:
                print(f"\n>> BEATS {name} ({vals['accuracy']:.3f})")

    print(f"\nTop 5 features:")
    for _, row in output["feature_importance"].head(5).iterrows():
        print(f"  {row['feature']:<35} {row['importance']:.0f}")
    print("=" * 60)


if __name__ == "__main__":
    main()

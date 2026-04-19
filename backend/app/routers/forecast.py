import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.evaluation_metric import EvaluationMetric
from app.models.forecast import ForecastRun, ForecastValue
from app.models.location import Location
from app.models.model_prediction import ModelPrediction
from app.prediction import get_comparison, get_forecast_summary, get_metrics_summary, get_predictions

log = logging.getLogger("forecast_router")

router = APIRouter(prefix="/api")

VALID_LOCATIONS = {"base", "mid", "alpine"}
LOC_IDS = {"base": 1, "mid": 2, "alpine": 3}
LOC_NAMES = {1: "base", 2: "mid", 3: "alpine"}

BASELINES = {
    "snowfall_24h": {"mae": 1.742},
    "wind_6h": {"mae": 8.229},
    "wind_12h": {"mae": 9.1},
    "freezing_level": {"mae": 379.192},
    "precip_type": {"accuracy": 0.875},
}
DRIFT_THRESHOLD = 1.5


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------


def _parse_dt(s: str) -> datetime:
    """Parse ISO datetime, handling URL-decoded '+' -> space."""
    s = s.strip().replace(" ", "+")
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {s!r}. Use ISO 8601.") from e


def _validate_location(location: str | None) -> str | None:
    if location is not None and location not in VALID_LOCATIONS:
        raise HTTPException(status_code=400, detail=f"Invalid location: {location!r}. Must be one of: {VALID_LOCATIONS}")
    return location


def _validate_date_range(start: datetime, end: datetime):
    if end < start:
        raise HTTPException(status_code=400, detail="end must be after start")
    if (end - start).days > 365:
        raise HTTPException(status_code=400, detail="Date range too large (max 365 days)")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class PredictionOut(BaseModel):
    time: str
    target: str
    location: str
    value: float | str | None
    unit: str
    confidence: float | None = None


class ComparisonOut(BaseModel):
    time: str
    raw_gfs_snowfall_cm: float | None
    corrected_snowfall_cm: float | None
    observed_snowfall_cm: float | None


class ForecastCurrentOut(BaseModel):
    status: str
    message: str | None = None
    run_at: str | None = None
    fetched_at: str | None = None
    prediction_count: int | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_stored_predictions(db: Session, start: datetime, end: datetime,
                            location: str | None) -> list[dict] | None:
    query = select(ModelPrediction).where(
        ModelPrediction.target_time >= start,
        ModelPrediction.target_time <= end,
    ).order_by(ModelPrediction.target_time)

    if location:
        loc_id = LOC_IDS.get(location)
        if loc_id:
            query = query.where(ModelPrediction.location_id == loc_id)

    rows = db.execute(query).scalars().all()
    if not rows:
        return None

    return [
        {
            "time": r.target_time.isoformat(),
            "target": r.target_name,
            "location": LOC_NAMES.get(r.location_id, "unknown"),
            "value": r.predicted_value if r.predicted_value is not None else r.predicted_class,
            "unit": "",
            "confidence": r.confidence,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/forecast/current", response_model=ForecastCurrentOut)
def current_forecast(db: Session = Depends(get_db)):
    """Return info about the latest forecast run."""
    try:
        run = db.execute(
            select(ForecastRun)
            .where(ForecastRun.model_name == "gfs_live")
            .order_by(ForecastRun.run_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    except Exception:
        log.exception("Failed to query forecast runs")
        raise HTTPException(status_code=503, detail="Database error")

    if not run:
        return ForecastCurrentOut(status="no_live_data", message="Run ingest_live_forecast.py first.")

    pred_count = db.execute(
        select(func.count(ModelPrediction.id))
        .where(ModelPrediction.forecast_run_id == run.id)
    ).scalar()

    return ForecastCurrentOut(
        status="ok", run_at=run.run_at.isoformat(),
        fetched_at=run.fetched_at.isoformat(), prediction_count=pred_count,
    )


@router.get("/forecast/summary")
def forecast_summary(
    location: str = Query("alpine"),
    db: Session = Depends(get_db),
):
    """Skier-optimized summary: snowfall, temperature, wind, conditions in one call."""
    _validate_location(location)
    try:
        return get_forecast_summary(db, location=location)
    except Exception:
        log.exception("Forecast summary failed")
        raise HTTPException(status_code=503, detail="Forecast summary unavailable")


@router.get("/forecast/stats")
def forecast_stats(db: Session = Depends(get_db)):
    try:
        rows = db.execute(
            select(
                ForecastRun.provider,
                ForecastRun.model_name,
                func.count(ForecastRun.id.distinct()).label("run_count"),
                func.count(ForecastValue.id).label("value_count"),
                func.min(ForecastRun.run_at).label("earliest_run"),
                func.max(ForecastRun.run_at).label("latest_run"),
            )
            .join(ForecastValue, ForecastValue.forecast_run_id == ForecastRun.id)
            .group_by(ForecastRun.provider, ForecastRun.model_name)
            .order_by(ForecastRun.provider, ForecastRun.model_name)
        ).all()
    except Exception:
        log.exception("Failed to query forecast stats")
        raise HTTPException(status_code=503, detail="Database error")

    return [
        {
            "provider": r.provider,
            "model_name": r.model_name,
            "run_count": r.run_count,
            "value_count": r.value_count,
            "earliest_run": r.earliest_run.isoformat() if r.earliest_run else None,
            "latest_run": r.latest_run.isoformat() if r.latest_run else None,
        }
        for r in rows
    ]


@router.get("/forecast/stats/by-location")
def forecast_stats_by_location(db: Session = Depends(get_db)):
    try:
        rows = db.execute(
            select(
                Location.name,
                ForecastRun.model_name,
                func.count(ForecastValue.id).label("value_count"),
                func.min(ForecastValue.valid_at).label("earliest"),
                func.max(ForecastValue.valid_at).label("latest"),
            )
            .join(ForecastValue, ForecastValue.forecast_run_id == ForecastRun.id)
            .join(Location, Location.id == ForecastValue.location_id)
            .group_by(Location.name, ForecastRun.model_name)
            .order_by(Location.name, ForecastRun.model_name)
        ).all()
    except Exception:
        log.exception("Failed to query forecast stats by location")
        raise HTTPException(status_code=503, detail="Database error")

    return [
        {
            "location": r.name,
            "model_name": r.model_name,
            "value_count": r.value_count,
            "earliest": r.earliest.isoformat() if r.earliest else None,
            "latest": r.latest.isoformat() if r.latest else None,
        }
        for r in rows
    ]


@router.get("/predictions")
def predictions(
    start: str = Query(None, description="Start ISO datetime"),
    end: str = Query(None, description="End ISO datetime"),
    location: str = Query(None, description="Location: alpine, mid, or base"),
    db: Session = Depends(get_db),
):
    """Get ML-corrected predictions. Serves from pre-computed table if available."""
    _validate_location(location)

    if not start:
        now = datetime.now(timezone.utc)
        start_dt = now
        end_dt = now + timedelta(hours=48)
    else:
        start_dt = _parse_dt(start)
        end_dt = _parse_dt(end) if end else start_dt + timedelta(hours=48)
        _validate_date_range(start_dt, end_dt)

    try:
        stored = _get_stored_predictions(db, start_dt, end_dt, location)
        if stored:
            return stored
        return get_predictions(db, start_dt, end_dt, location=location)
    except Exception:
        log.exception("Prediction failed for %s to %s, location=%s", start_dt, end_dt, location)
        raise HTTPException(status_code=503, detail="Prediction service unavailable. Models may not be loaded.")


@router.get("/predictions/latest")
def predictions_latest(
    location: str = Query(None),
    db: Session = Depends(get_db),
):
    """Get the latest pre-computed predictions (next 48h from most recent run)."""
    _validate_location(location)

    try:
        run = db.execute(
            select(ForecastRun)
            .where(ForecastRun.model_name == "gfs_live")
            .order_by(ForecastRun.run_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    except Exception:
        log.exception("Failed to query latest forecast run")
        raise HTTPException(status_code=503, detail="Database error")

    if not run:
        return []

    start = run.run_at
    end = run.run_at + timedelta(hours=48)
    stored = _get_stored_predictions(db, start, end, location)
    return stored or []


@router.get("/comparison")
def comparison(
    start: str = Query(None),
    end: str = Query(None),
    location: str = Query("alpine", description="Location: alpine, mid, or base"),
    db: Session = Depends(get_db),
):
    """Compare raw GFS vs corrected vs observed snowfall."""
    _validate_location(location)

    if not start:
        now = datetime.now(timezone.utc)
        end_dt = now
        start_dt = now - timedelta(hours=72)
    else:
        start_dt = _parse_dt(start)
        end_dt = _parse_dt(end) if end else start_dt + timedelta(hours=72)
        _validate_date_range(start_dt, end_dt)

    try:
        return get_comparison(db, start_dt, end_dt, location=location)
    except Exception:
        log.exception("Comparison failed for %s to %s", start_dt, end_dt)
        raise HTTPException(status_code=503, detail="Comparison service unavailable")


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)):
    """Get model performance metrics."""
    try:
        return get_metrics_summary(db)
    except Exception:
        log.exception("Failed to load metrics")
        raise HTTPException(status_code=503, detail="Metrics unavailable")


@router.get("/performance")
def performance(db: Session = Depends(get_db)):
    """Rolling performance metrics from live evaluation."""
    now = datetime.now(timezone.utc)

    def _get_rolling(days: int) -> dict:
        cutoff = now - timedelta(days=days)
        rows = db.execute(
            select(EvaluationMetric)
            .where(EvaluationMetric.evaluated_at >= cutoff, EvaluationMetric.horizon_hours.is_(None))
        ).scalars().all()

        result = {}
        for r in rows:
            loc = LOC_NAMES.get(r.location_id, "unknown")
            if r.target_name not in result:
                result[r.target_name] = {}
            result[r.target_name][loc] = {
                "mae": r.mae,
                "rmse": r.rmse,
                "accuracy": r.accuracy,
                "n": r.n_samples,
                "evaluated_at": r.evaluated_at.isoformat() if r.evaluated_at else None,
            }
        return result

    try:
        rolling_7d = _get_rolling(7)
        rolling_30d = _get_rolling(30)
    except Exception:
        log.exception("Failed to query performance metrics")
        raise HTTPException(status_code=503, detail="Database error")

    drift_alerts = []
    for target, locs in rolling_7d.items():
        baseline = BASELINES.get(target, {})
        for loc, vals in locs.items():
            if vals.get("mae") and baseline.get("mae"):
                ratio = vals["mae"] / baseline["mae"]
                if ratio > DRIFT_THRESHOLD:
                    drift_alerts.append({
                        "target": target, "location": loc,
                        "rolling_mae": vals["mae"], "baseline_mae": baseline["mae"],
                        "ratio": round(ratio, 2),
                    })
            if vals.get("accuracy") and baseline.get("accuracy"):
                if vals["accuracy"] < baseline["accuracy"] * 0.8:
                    drift_alerts.append({
                        "target": target, "location": loc,
                        "rolling_accuracy": vals["accuracy"],
                        "baseline_accuracy": baseline["accuracy"],
                    })

    return {
        "rolling_7d": rolling_7d,
        "rolling_30d": rolling_30d,
        "baselines": BASELINES,
        "drift_alerts": drift_alerts,
    }


@router.get("/performance/trend")
def performance_trend(
    target: str = Query("snowfall_24h"),
    location: str = Query("alpine"),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Daily MAE trend for a specific target/location."""
    _validate_location(location)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    loc_id = LOC_IDS.get(location, 3)

    try:
        rows = db.execute(
            select(EvaluationMetric)
            .where(
                EvaluationMetric.target_name == target,
                EvaluationMetric.location_id == loc_id,
                EvaluationMetric.evaluated_at >= cutoff,
                EvaluationMetric.horizon_hours.is_(None),
            )
            .order_by(EvaluationMetric.evaluated_at)
        ).scalars().all()
    except Exception:
        log.exception("Failed to query performance trend")
        raise HTTPException(status_code=503, detail="Database error")

    return [
        {
            "date": r.evaluated_at.date().isoformat(),
            "mae": r.mae, "rmse": r.rmse,
            "accuracy": r.accuracy, "n": r.n_samples,
        }
        for r in rows
    ]

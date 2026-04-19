from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter()

MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "models"


@router.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"
    return {"status": "ok", "database": db_status}


@router.get("/health/detailed")
def health_detailed(db: Session = Depends(get_db)):
    """Detailed health check for monitoring."""
    checks = {}

    # Database
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Data freshness
    try:
        row = db.execute(text(
            "SELECT MAX(observed_at) FROM obs_hourly"
        )).scalar()
        checks["latest_observation"] = row.isoformat() if row else "no data"
        if row:
            age_hours = (datetime.now(timezone.utc) - row).total_seconds() / 3600
            checks["obs_age_hours"] = round(age_hours, 1)
    except Exception as e:
        checks["latest_observation"] = f"error: {e}"

    try:
        row = db.execute(text(
            "SELECT MAX(run_at) FROM forecast_runs WHERE provider = 'open_meteo'"
        )).scalar()
        checks["latest_forecast_run"] = row.isoformat() if row else "no data"
    except Exception as e:
        checks["latest_forecast_run"] = f"error: {e}"

    # Row counts
    try:
        checks["obs_count"] = db.execute(text("SELECT COUNT(*) FROM obs_hourly")).scalar()
        checks["forecast_value_count"] = db.execute(text("SELECT COUNT(*) FROM forecast_values")).scalar()
        checks["label_count"] = db.execute(text("SELECT COUNT(*) FROM training_labels")).scalar()
    except Exception as e:
        checks["counts"] = f"error: {e}"

    # Model files
    model_files = list(MODEL_DIR.glob("*.pkl")) if MODEL_DIR.exists() else []
    checks["models_loaded"] = len(model_files)
    checks["model_names"] = [f.stem for f in model_files]

    return {"status": "ok" if checks.get("database") == "ok" else "degraded", **checks}

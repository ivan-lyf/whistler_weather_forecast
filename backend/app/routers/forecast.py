from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.forecast import ForecastRun, ForecastValue
from app.models.location import Location

router = APIRouter(prefix="/api")


@router.get("/forecast/current")
def current_forecast():
    return {"message": "No live forecast data yet. Ingest data first."}


@router.get("/forecast/stats")
def forecast_stats(db: Session = Depends(get_db)):
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

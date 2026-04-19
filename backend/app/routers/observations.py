import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.observation import ObsHourly
from app.models.station import Station

log = logging.getLogger("observations_router")

router = APIRouter(prefix="/api")


@router.get("/observations/stats")
def observation_stats(db: Session = Depends(get_db)):
    try:
        rows = db.execute(
            select(
                Station.id,
                Station.source,
                Station.name,
                func.count(ObsHourly.id).label("row_count"),
                func.min(ObsHourly.observed_at).label("earliest"),
                func.max(ObsHourly.observed_at).label("latest"),
            )
            .join(ObsHourly, ObsHourly.station_id == Station.id)
            .group_by(Station.id, Station.source, Station.name)
            .order_by(Station.source, Station.name)
        ).all()
    except Exception:
        log.exception("Failed to query observation stats")
        raise HTTPException(status_code=503, detail="Database error")

    return [
        {
            "station_id": r.id,
            "source": r.source,
            "name": r.name,
            "row_count": r.row_count,
            "earliest": r.earliest.isoformat() if r.earliest else None,
            "latest": r.latest.isoformat() if r.latest else None,
        }
        for r in rows
    ]

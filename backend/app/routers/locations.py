from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.location import Location

router = APIRouter(prefix="/api")


class LocationOut(BaseModel):
    id: int
    name: str
    latitude: float
    longitude: float
    elevation_m: int

    model_config = {"from_attributes": True}


@router.get("/locations", response_model=list[LocationOut])
def list_locations(db: Session = Depends(get_db)):
    return db.query(Location).order_by(Location.elevation_m).all()

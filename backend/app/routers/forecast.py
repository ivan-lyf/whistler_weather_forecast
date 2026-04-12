from fastapi import APIRouter

router = APIRouter(prefix="/api")


@router.get("/forecast/current")
def current_forecast():
    return {"message": "No forecast data yet. Ingest data first."}

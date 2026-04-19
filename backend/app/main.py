import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import alerts, forecast, health, locations, observations

log = logging.getLogger("app")

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
REQUIRED_MODELS = [
    "snowfall_24h_alpine",
    "wind_6h_alpine",
    "wind_12h_alpine",
    "freezing_level_base",
    "precip_type_alpine",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: validate model files exist
    missing = [m for m in REQUIRED_MODELS if not (MODEL_DIR / f"{m}.pkl").exists()]
    if missing:
        log.warning("Missing model files: %s — prediction endpoints will fail for these targets", missing)
    else:
        log.info("All %d model files found", len(REQUIRED_MODELS))
    yield


app = FastAPI(title="Whistler Forecast", version="0.1.0", lifespan=lifespan)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(locations.router)
app.include_router(forecast.router)
app.include_router(observations.router)
app.include_router(alerts.router)

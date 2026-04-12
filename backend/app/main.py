from fastapi import FastAPI

from app.routers import forecast, health, locations, observations

app = FastAPI(title="Whistler Forecast", version="0.1.0")

app.include_router(health.router)
app.include_router(locations.router)
app.include_router(forecast.router)
app.include_router(observations.router)

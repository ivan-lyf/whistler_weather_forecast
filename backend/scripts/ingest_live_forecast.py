"""Ingest the latest live GFS forecast from Open-Meteo Forecast API.

Unlike the historical forecast ingestion (which fetches archived past forecasts),
this script fetches the CURRENT forecast for the next 7 days. This is what powers
real-time predictions on the dashboard.

Usage:
    python scripts/ingest_live_forecast.py [--forecast-days 7] [--verbose]
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.database import SessionLocal
from app.models.forecast import ForecastRun, ForecastValue
from app.models.location import Location

log = logging.getLogger("ingest_live")

FORECAST_HOURLY_VARS = [
    "temperature_2m",
    "precipitation",
    "snowfall",
    "wind_speed_10m",
    "wind_gusts_10m",
    "relative_humidity_2m",
    "surface_pressure",
    "freezing_level_height",
    "weather_code",
]

# GFS runs at 00, 06, 12, 18 UTC. Round down to nearest 6h for run_at.
def _estimate_run_at() -> datetime:
    now = datetime.now(timezone.utc)
    hour = (now.hour // 6) * 6
    return now.replace(hour=hour, minute=0, second=0, microsecond=0)


def upsert_forecast_run(db, provider: str, model_name: str, run_at: datetime,
                        fetched_at: datetime, raw_payload: dict) -> tuple[int, bool]:
    existing = db.execute(
        select(ForecastRun).where(
            ForecastRun.provider == provider,
            ForecastRun.model_name == model_name,
            ForecastRun.run_at == run_at,
        )
    ).scalar_one_or_none()
    if existing:
        return existing.id, False

    run = ForecastRun(
        provider=provider, model_name=model_name,
        run_at=run_at, fetched_at=fetched_at,
        raw_payload=raw_payload,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run.id, True


LIVE_MODELS = [
    ("gfs_live", None),              # default GFS (no models param)
    ("ecmwf_live", "ecmwf_ifs025"),  # ECMWF IFS 0.25°
]


def ingest_live_forecast(db, client: httpx.Client, forecast_days: int = 7):
    locations = db.execute(select(Location).order_by(Location.id)).scalars().all()
    if not locations:
        log.error("No locations in database")
        return

    run_at = _estimate_run_at()
    fetched_at = datetime.now(timezone.utc)
    log.info("Estimated run_at: %s", run_at)

    total_values = 0

    for model_db_name, api_model in LIVE_MODELS:
        log.info("--- Fetching model: %s ---", model_db_name)

        for location in locations:
            log.info("Fetching %s for %s...", model_db_name, location.name)

            params = {
                "latitude": location.latitude,
                "longitude": location.longitude,
                "hourly": ",".join(FORECAST_HOURLY_VARS),
                "forecast_days": forecast_days,
                "timezone": "UTC",
            }
            if api_model:
                params["models"] = api_model

            try:
                resp = client.get(settings.openmeteo_base_url + "/forecast", params=params)
                resp.raise_for_status()
            except httpx.HTTPError as e:
                log.error("API request failed for %s/%s: %s", model_db_name, location.name, e)
                continue

            data = resp.json()
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])

            if not times:
                log.warning("No data returned for %s/%s", model_db_name, location.name)
                continue

            run_payload = {
                "source": "live-forecast-api",
                "model": api_model or "gfs_seamless",
                "location": location.name,
                "forecast_days": forecast_days,
                "elevation": data.get("elevation"),
            }

            run_id, is_new = upsert_forecast_run(
                db, "open_meteo", model_db_name, run_at, fetched_at, run_payload
            )

            if not is_new:
                from sqlalchemy import func
                existing_count = db.execute(
                    select(func.count(ForecastValue.id)).where(
                        ForecastValue.forecast_run_id == run_id,
                        ForecastValue.location_id == location.id,
                    )
                ).scalar()
                if existing_count > 0:
                    log.info("%s/%s: already populated (%d values), skipping",
                             model_db_name, location.name, existing_count)
                    continue

            # Validate timezone
            api_tz = data.get("timezone", "")
            if api_tz not in ("GMT", "UTC", ""):
                log.warning("Unexpected timezone: %s", api_tz)

            rows = []
            for i, time_str in enumerate(times):
                valid_at = datetime.strptime(time_str, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
                lead_hours = int((valid_at - run_at).total_seconds() / 3600)

                wc = hourly.get("weather_code", [None] * len(times))[i]
                rows.append({
                    "forecast_run_id": run_id,
                    "location_id": location.id,
                    "valid_at": valid_at,
                    "lead_hours": max(lead_hours, 0),
                    "temperature_c": hourly.get("temperature_2m", [None] * len(times))[i],
                    "precip_mm": hourly.get("precipitation", [None] * len(times))[i],
                    "snowfall_cm": hourly.get("snowfall", [None] * len(times))[i],
                    "wind_speed_kmh": hourly.get("wind_speed_10m", [None] * len(times))[i],
                    "wind_gust_kmh": hourly.get("wind_gusts_10m", [None] * len(times))[i],
                    "humidity_pct": hourly.get("relative_humidity_2m", [None] * len(times))[i],
                    "pressure_hpa": hourly.get("surface_pressure", [None] * len(times))[i],
                    "freezing_level_m": hourly.get("freezing_level_height", [None] * len(times))[i],
                    "weather_code": int(wc) if wc is not None else None,
                })

            if rows:
                batch_size = 500
                inserted = 0
                for j in range(0, len(rows), batch_size):
                    batch = rows[j:j + batch_size]
                    stmt = pg_insert(ForecastValue.__table__).values(batch)
                    stmt = stmt.on_conflict_do_nothing()
                    db.execute(stmt)
                    db.commit()
                    inserted += len(batch)
                total_values += inserted

            log.info("%s/%s: inserted %d values", model_db_name, location.name, len(rows))
            time.sleep(0.5)

    log.info("Complete. Total values inserted: %d", total_values)


def main():
    parser = argparse.ArgumentParser(description="Ingest live GFS forecast")
    parser.add_argument("--forecast-days", type=int, default=7, help="Days to forecast (default: 7)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    db = SessionLocal()
    client = httpx.Client(timeout=30.0)

    try:
        ingest_live_forecast(db, client, args.forecast_days)
    finally:
        client.close()
        db.close()

    log.info("Done.")


if __name__ == "__main__":
    main()

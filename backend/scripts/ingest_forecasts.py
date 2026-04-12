"""Ingest archived forecast data from Open-Meteo Historical Forecast API."""

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone
from itertools import groupby
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.database import SessionLocal
from app.models.forecast import ForecastRun, ForecastValue
from app.models.location import Location

log = logging.getLogger("ingest_forecasts")

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fetch_with_retries(client: httpx.Client, url: str, params: dict, max_attempts: int = 3) -> httpx.Response:
    for attempt in range(max_attempts):
        try:
            resp = client.get(url, params=params)
            if resp.status_code == 429:
                wait = 60
                log.warning("Rate limited (429), sleeping %ds...", wait)
                time.sleep(wait)
                continue
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                resp.raise_for_status()
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError:
            raise
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            if attempt == max_attempts - 1:
                raise
            wait = 2.0 * (2**attempt)
            log.warning("Request failed (%s), retrying in %.1fs...", e, wait)
            time.sleep(wait)
    raise RuntimeError("Unreachable")


def get_locations(db, name_filter: str | None = None) -> list:
    stmt = select(Location)
    if name_filter:
        stmt = stmt.where(Location.name == name_filter)
    stmt = stmt.order_by(Location.id)
    return list(db.execute(stmt).scalars().all())


def date_chunks(start: date, end: date, months: int = 3) -> list[tuple[date, date]]:
    chunks = []
    current = start
    while current <= end:
        # Advance by N months
        month = current.month + months
        year = current.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        chunk_end = date(year, month, 1) - timedelta(days=1)
        if chunk_end > end:
            chunk_end = end
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks


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
        provider=provider,
        model_name=model_name,
        run_at=run_at,
        fetched_at=fetched_at,
        raw_payload=raw_payload,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run.id, True


def bulk_insert_forecast_values(db, rows: list[dict]) -> int:
    if not rows:
        return 0
    batch_size = 1000
    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        db.execute(pg_insert(ForecastValue.__table__).values(batch))
        db.commit()
        total += len(batch)
    return total


# ---------------------------------------------------------------------------
# Historical forecast ingestion
# ---------------------------------------------------------------------------


def ingest_historical_forecast(
    db,
    client: httpx.Client,
    start: date,
    end: date,
    model: str = "gfs",
    chunk_months: int = 3,
    location_filter: str | None = None,
):
    locations = get_locations(db, location_filter)
    if not locations:
        log.error("No locations found%s", f" matching '{location_filter}'" if location_filter else "")
        return

    log.info("Locations: %s", [loc.name for loc in locations])

    chunks = date_chunks(start, end, chunk_months)
    log.info("Date range %s to %s split into %d chunks", start, end, len(chunks))

    fetched_at = datetime.now(timezone.utc)
    total_runs = 0
    total_values = 0
    skipped_runs = 0

    for chunk_idx, (chunk_start, chunk_end) in enumerate(chunks):
        for location in locations:
            log.info(
                "Chunk %d/%d: %s to %s, location=%s (%.4f, %.4f)",
                chunk_idx + 1, len(chunks), chunk_start, chunk_end,
                location.name, location.latitude, location.longitude,
            )

            params = {
                "latitude": location.latitude,
                "longitude": location.longitude,
                "start_date": chunk_start.isoformat(),
                "end_date": chunk_end.isoformat(),
                "hourly": ",".join(FORECAST_HOURLY_VARS),
                "model": model,
                "timezone": "UTC",
            }

            resp = fetch_with_retries(client, settings.openmeteo_historical_forecast_url, params)
            data = resp.json()

            if "error" in data:
                log.error("API error: %s", data["error"])
                continue

            hourly = data.get("hourly", {})
            times = hourly.get("time", [])

            if not times:
                log.warning("No data returned for %s %s-%s", location.name, chunk_start, chunk_end)
                continue

            # Group time entries by date
            time_entries = []
            for i, time_str in enumerate(times):
                valid_at = datetime.strptime(time_str, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
                vals = {}
                for var in FORECAST_HOURLY_VARS:
                    arr = hourly.get(var, [])
                    vals[var] = arr[i] if i < len(arr) else None
                time_entries.append((valid_at, vals))

            for day_date, day_group in groupby(time_entries, key=lambda x: x[0].date()):
                day_entries = list(day_group)
                run_at = datetime(day_date.year, day_date.month, day_date.day, tzinfo=timezone.utc)

                run_payload = {
                    "source": "historical-forecast-api",
                    "model": model,
                    "date": day_date.isoformat(),
                    "lat": location.latitude,
                    "lon": location.longitude,
                }

                run_id, is_new = upsert_forecast_run(db, "open_meteo", model, run_at, fetched_at, run_payload)

                if not is_new:
                    # Check if values exist for this location already
                    existing_count = db.execute(
                        select(func.count(ForecastValue.id)).where(
                            ForecastValue.forecast_run_id == run_id,
                            ForecastValue.location_id == location.id,
                        )
                    ).scalar()
                    if existing_count > 0:
                        skipped_runs += 1
                        continue

                value_rows = []
                for valid_at, vals in day_entries:
                    wc = vals.get("weather_code")
                    value_rows.append({
                        "forecast_run_id": run_id,
                        "location_id": location.id,
                        "valid_at": valid_at,
                        "lead_hours": valid_at.hour,
                        "temperature_c": vals.get("temperature_2m"),
                        "precip_mm": vals.get("precipitation"),
                        "snowfall_cm": vals.get("snowfall"),
                        "wind_speed_kmh": vals.get("wind_speed_10m"),
                        "wind_gust_kmh": vals.get("wind_gusts_10m"),
                        "humidity_pct": vals.get("relative_humidity_2m"),
                        "pressure_hpa": vals.get("surface_pressure"),
                        "freezing_level_m": vals.get("freezing_level_height"),
                        "weather_code": int(wc) if wc is not None else None,
                    })

                inserted = bulk_insert_forecast_values(db, value_rows)
                total_runs += 1
                total_values += inserted

            log.info(
                "Chunk %d/%d %s: %d hours fetched (runs so far: %d, values: %d, skipped: %d)",
                chunk_idx + 1, len(chunks), location.name,
                len(times), total_runs, total_values, skipped_runs,
            )

            time.sleep(1.0)

    log.info("Complete. total_runs=%d, total_values=%d, skipped_runs=%d", total_runs, total_values, skipped_runs)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Ingest archived forecast data")
    parser.add_argument("source", choices=["historical", "all"], help="Data source to ingest")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2022, 1, 1), help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=date.fromisoformat, default=None, help="End date (YYYY-MM-DD), defaults to yesterday")
    parser.add_argument("--model", default="gfs_seamless", help="Forecast model (default: gfs_seamless)")
    parser.add_argument("--chunk-months", type=int, default=3, help="Months per API chunk (default: 3)")
    parser.add_argument("--location", default=None, help="Filter by location name (e.g., alpine)")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.end is None:
        args.end = date.today() - timedelta(days=1)

    log.info("Ingesting %s forecasts (%s) from %s to %s", args.source, args.model, args.start, args.end)

    db = SessionLocal()
    client = httpx.Client(timeout=60.0)

    try:
        if args.source in ("historical", "all"):
            ingest_historical_forecast(db, client, args.start, args.end, args.model, args.chunk_months, args.location)
    finally:
        client.close()
        db.close()

    log.info("Done.")


if __name__ == "__main__":
    main()

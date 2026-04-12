"""Ingest hourly weather observations from ECCC and Open-Meteo into the database."""

import argparse
import logging
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.database import SessionLocal
from app.models.observation import ObsHourly
from app.models.station import Station

log = logging.getLogger("ingest")

ECCC_STATIONS = [
    {
        "source": "eccc",
        "external_station_id": "348",
        "name": "WHISTLER",
        "latitude": 50.1289,
        "longitude": -122.9548,
        "elevation_m": 658,
        "is_active": False,
    },
    {
        "source": "eccc",
        "external_station_id": "43443",
        "name": "WHISTLER - NESTERS",
        "latitude": 50.1354,
        "longitude": -122.9533,
        "elevation_m": 659,
        "is_active": True,
    },
]

OPENMETEO_STATIONS = [
    {
        "source": "open_meteo",
        "external_station_id": "whistler_base",
        "name": "Open-Meteo Whistler Base",
        "latitude": 50.1145,
        "longitude": -122.9540,
        "elevation_m": 675,
        "is_active": True,
    },
    {
        "source": "open_meteo",
        "external_station_id": "whistler_mid",
        "name": "Open-Meteo Whistler Mid",
        "latitude": 50.1070,
        "longitude": -122.9480,
        "elevation_m": 1500,
        "is_active": True,
    },
    {
        "source": "open_meteo",
        "external_station_id": "whistler_alpine",
        "name": "Open-Meteo Whistler Alpine",
        "latitude": 50.0990,
        "longitude": -122.9420,
        "elevation_m": 2200,
        "is_active": True,
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def upsert_station(db, **kwargs) -> int:
    existing = db.execute(
        select(Station).where(
            Station.source == kwargs["source"],
            Station.external_station_id == kwargs["external_station_id"],
        )
    ).scalar_one_or_none()
    if existing:
        return existing.id
    station = Station(**kwargs)
    db.add(station)
    db.commit()
    db.refresh(station)
    log.info("Registered station: %s (id=%d)", kwargs["name"], station.id)
    return station.id


def bulk_insert_obs(db, rows: list[dict]) -> int:
    if not rows:
        return 0
    stmt = pg_insert(ObsHourly.__table__).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["station_id", "observed_at"])
    db.execute(stmt)
    db.commit()
    return len(rows)


def fetch_with_retries(client: httpx.Client, url: str, params: dict, max_attempts: int = 3) -> httpx.Response:
    for attempt in range(max_attempts):
        try:
            resp = client.get(url, params=params)
            if resp.status_code == 429:
                wait = 60
                log.warning("Rate limited (429), sleeping %ds...", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            if attempt == max_attempts - 1:
                raise
            wait = 2.0 * (2**attempt)
            log.warning("Request failed (%s), retrying in %.1fs...", e, wait)
            time.sleep(wait)
    raise RuntimeError("Unreachable")


# ---------------------------------------------------------------------------
# ECCC ingestion
# ---------------------------------------------------------------------------


def parse_eccc_utc_date(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse ECCC UTC_DATE: {value!r}")


def ingest_eccc(db, client: httpx.Client, start: date, end: date, station_filter: str | None = None):
    stations_to_ingest = ECCC_STATIONS
    if station_filter:
        stations_to_ingest = [s for s in ECCC_STATIONS if s["external_station_id"] == station_filter]
        if not stations_to_ingest:
            log.error("No ECCC station with ID %s", station_filter)
            return

    for station_def in stations_to_ingest:
        station_id = upsert_station(db, **station_def)
        stn_id = station_def["external_station_id"]
        name = station_def["name"]
        log.info("[eccc] Starting ingestion for %s (STN_ID=%s)", name, stn_id)

        datetime_filter = f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z"
        offset = 0
        total_inserted = 0

        while True:
            params = {
                "STN_ID": stn_id,
                "datetime": datetime_filter,
                "sortby": "LOCAL_DATE",
                "limit": 500,
                "offset": offset,
                "f": "json",
            }

            resp = fetch_with_retries(
                client,
                f"{settings.geomet_base_url}/collections/climate-hourly/items",
                params,
            )
            data = resp.json()
            features = data.get("features", [])

            if not features:
                break

            rows = []
            for feature in features:
                props = feature.get("properties", {})
                utc_date = props.get("UTC_DATE")
                if not utc_date:
                    continue

                try:
                    observed_at = parse_eccc_utc_date(utc_date)
                except ValueError:
                    log.warning("Skipping unparseable UTC_DATE: %s", utc_date)
                    continue

                pressure_kpa = props.get("STATION_PRESSURE")
                rows.append({
                    "station_id": station_id,
                    "observed_at": observed_at,
                    "temperature_c": props.get("TEMP"),
                    "precip_mm": props.get("PRECIP_AMOUNT"),
                    "snowfall_cm": None,
                    "snow_depth_cm": None,
                    "wind_speed_kmh": props.get("WIND_SPEED"),
                    "wind_gust_kmh": None,
                    "humidity_pct": props.get("RELATIVE_HUMIDITY"),
                    "pressure_hpa": round(pressure_kpa * 10, 1) if pressure_kpa is not None else None,
                    "raw_payload": props,
                })

            inserted = bulk_insert_obs(db, rows)
            total_inserted += inserted
            log.info("[eccc] %s: offset=%d, fetched=%d, inserted=%d", name, offset, len(features), inserted)

            if len(features) < 500:
                break

            offset += 500
            time.sleep(0.5)

        log.info("[eccc] %s: complete. total_inserted=%d", name, total_inserted)


# ---------------------------------------------------------------------------
# Open-Meteo ingestion
# ---------------------------------------------------------------------------

OPENMETEO_HOURLY_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "snowfall",
    "snow_depth",
    "wind_speed_10m",
    "wind_gusts_10m",
    "surface_pressure",
    "weather_code",
]


def ingest_openmeteo(db, client: httpx.Client, start: date, end: date):
    for station_def in OPENMETEO_STATIONS:
        station_id = upsert_station(db, **station_def)
        name = station_def["name"]
        log.info("[open_meteo] Fetching %s: %s to %s...", name, start, end)

        params = {
            "latitude": station_def["latitude"],
            "longitude": station_def["longitude"],
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": ",".join(OPENMETEO_HOURLY_VARS),
            "timezone": "UTC",
        }

        resp = fetch_with_retries(client, settings.openmeteo_archive_url, params)
        data = resp.json()
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])

        if not times:
            log.warning("[open_meteo] %s: No data returned", name)
            continue

        total_inserted = 0
        batch = []

        for i, time_str in enumerate(times):
            observed_at = datetime.strptime(time_str, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)

            snow_depth_m = hourly.get("snow_depth", [None] * len(times))[i]
            raw = {var: hourly.get(var, [None] * len(times))[i] for var in OPENMETEO_HOURLY_VARS}

            batch.append({
                "station_id": station_id,
                "observed_at": observed_at,
                "temperature_c": hourly.get("temperature_2m", [None] * len(times))[i],
                "precip_mm": hourly.get("precipitation", [None] * len(times))[i],
                "snowfall_cm": hourly.get("snowfall", [None] * len(times))[i],
                "snow_depth_cm": round(snow_depth_m * 100, 1) if snow_depth_m is not None else None,
                "wind_speed_kmh": hourly.get("wind_speed_10m", [None] * len(times))[i],
                "wind_gust_kmh": hourly.get("wind_gusts_10m", [None] * len(times))[i],
                "humidity_pct": hourly.get("relative_humidity_2m", [None] * len(times))[i],
                "pressure_hpa": hourly.get("surface_pressure", [None] * len(times))[i],
                "raw_payload": raw,
            })

            if len(batch) >= 1000:
                inserted = bulk_insert_obs(db, batch)
                total_inserted += inserted
                log.info("[open_meteo] %s: batch inserted=%d (total=%d/%d)", name, inserted, total_inserted, i + 1)
                batch = []

        if batch:
            inserted = bulk_insert_obs(db, batch)
            total_inserted += inserted

        log.info("[open_meteo] %s: Complete. total_inserted=%d out of %d hours", name, total_inserted, len(times))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Ingest weather observations")
    parser.add_argument("source", choices=["eccc", "meteo", "all"], help="Data source to ingest")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2022, 1, 1), help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=date.fromisoformat, default=None, help="End date (YYYY-MM-DD), defaults to yesterday")
    parser.add_argument("--station-id", default=None, help="ECCC station ID filter (e.g., 43443)")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.end is None:
        args.end = date.today()

    log.info("Ingesting %s from %s to %s", args.source, args.start, args.end)

    db = SessionLocal()
    client = httpx.Client(timeout=30.0)

    try:
        if args.source in ("eccc", "all"):
            ingest_eccc(db, client, args.start, args.end, args.station_id)
        if args.source in ("meteo", "all"):
            ingest_openmeteo(db, client, args.start, args.end)
    finally:
        client.close()
        db.close()

    log.info("Done.")


if __name__ == "__main__":
    main()

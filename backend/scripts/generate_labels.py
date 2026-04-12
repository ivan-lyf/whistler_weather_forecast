"""Generate training labels from observation data."""

import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models.training_label import TrainingLabel

log = logging.getLogger("generate_labels")

# Station ID → Location ID mapping (by matching elevation)
STATION_LOCATION_MAP = {
    1: 1,   # Open-Meteo Base (675m) → location base
    4: 2,   # Open-Meteo Mid (1500m) → location mid
    5: 3,   # Open-Meteo Alpine (2200m) → location alpine
}

BASE_ELEVATION_M = 675
LAPSE_RATE_PER_M = 0.0065  # °C/m, environmental lapse rate


def load_observations(db, start: date, end: date) -> pd.DataFrame:
    """Load Open-Meteo observations for all 3 elevation stations."""
    query = text("""
        SELECT o.station_id, o.observed_at, o.temperature_c, o.precip_mm,
               o.snowfall_cm, o.wind_speed_kmh, o.wind_gust_kmh,
               s.elevation_m
        FROM obs_hourly o
        JOIN stations s ON s.id = o.station_id
        WHERE s.source = 'open_meteo'
          AND o.observed_at >= :start
          AND o.observed_at < :end
        ORDER BY o.station_id, o.observed_at
    """)
    rows = db.execute(query, {
        "start": datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
        "end": datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=1),
    }).all()

    df = pd.DataFrame(rows, columns=[
        "station_id", "observed_at", "temperature_c", "precip_mm",
        "snowfall_cm", "wind_speed_kmh", "wind_gust_kmh", "elevation_m",
    ])
    df["observed_at"] = pd.to_datetime(df["observed_at"], utc=True)
    return df


def load_base_eccc_temperature(db, start: date, end: date) -> pd.DataFrame:
    """Load ECCC base station temperature for freezing level derivation."""
    query = text("""
        SELECT o.observed_at, o.temperature_c
        FROM obs_hourly o
        JOIN stations s ON s.id = o.station_id
        WHERE s.source = 'eccc' AND s.external_station_id = '43443'
          AND o.observed_at >= :start
          AND o.observed_at < :end
        ORDER BY o.observed_at
    """)
    rows = db.execute(query, {
        "start": datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
        "end": datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=1),
    }).all()

    df = pd.DataFrame(rows, columns=["observed_at", "temperature_c"])
    df["observed_at"] = pd.to_datetime(df["observed_at"], utc=True)
    return df


def compute_labels(obs_df: pd.DataFrame, eccc_temp_df: pd.DataFrame) -> pd.DataFrame:
    """Compute all training labels from observations."""
    all_labels = []

    for station_id, location_id in STATION_LOCATION_MAP.items():
        stn = obs_df[obs_df["station_id"] == station_id].copy()
        if stn.empty:
            continue

        stn = stn.sort_values("observed_at").set_index("observed_at")

        # Ensure hourly frequency (fill gaps with NaN)
        full_idx = pd.date_range(stn.index.min(), stn.index.max(), freq="h", tz="UTC")
        stn = stn.reindex(full_idx)

        # 24h snowfall: rolling sum over past 24 hours
        label_24h_snow = stn["snowfall_cm"].rolling(24, min_periods=20).sum()

        # Wind: use gust if available, fallback to speed
        wind = stn["wind_gust_kmh"].fillna(stn["wind_speed_kmh"])
        label_6h_wind = wind.rolling(6, min_periods=5).max()
        label_12h_wind = wind.rolling(12, min_periods=10).max()

        # Precip type at this elevation
        temp = stn["temperature_c"]
        precip = stn["precip_mm"]
        has_precip = precip > 0.1
        precip_type = pd.Series(np.nan, index=stn.index, dtype=object)
        precip_type[has_precip & (temp < 0)] = "snow"
        precip_type[has_precip & (temp > 2)] = "rain"
        precip_type[has_precip & (temp >= 0) & (temp <= 2)] = "mixed"

        labels = pd.DataFrame({
            "location_id": location_id,
            "target_time": stn.index,
            "label_24h_snowfall_cm": label_24h_snow.values,
            "label_6h_wind_kmh": label_6h_wind.values,
            "label_12h_wind_kmh": label_12h_wind.values,
            "label_precip_type": precip_type.values,
        })
        all_labels.append(labels)

    # Freezing level from ECCC base temperature (location-independent)
    if not eccc_temp_df.empty:
        eccc = eccc_temp_df.copy().set_index("observed_at")
        full_idx = pd.date_range(eccc.index.min(), eccc.index.max(), freq="h", tz="UTC")
        eccc = eccc.reindex(full_idx)

        temp = eccc["temperature_c"]
        # Only derive when temperature is in reasonable range
        valid_mask = temp.between(-10, 10)
        freezing_level = pd.Series(np.nan, index=eccc.index)
        freezing_level[valid_mask] = BASE_ELEVATION_M + (temp[valid_mask] / LAPSE_RATE_PER_M)
        # Clamp to physically reasonable range
        freezing_level = freezing_level.clip(lower=0, upper=5000)

        fzl_df = pd.DataFrame({
            "target_time": eccc.index,
            "label_freezing_level_m": freezing_level.values,
        })
    else:
        fzl_df = pd.DataFrame(columns=["target_time", "label_freezing_level_m"])

    # Combine all location labels
    combined = pd.concat(all_labels, ignore_index=True)

    # Merge freezing level onto base location only (location_id=1)
    # but also assign to all locations since freezing level is universal
    if not fzl_df.empty:
        combined = combined.merge(fzl_df, on="target_time", how="left")
    else:
        combined["label_freezing_level_m"] = np.nan

    return combined


def insert_labels(db, labels_df: pd.DataFrame) -> int:
    """Bulk insert labels with ON CONFLICT DO NOTHING."""
    # Drop rows where all label columns are NaN
    label_cols = ["label_24h_snowfall_cm", "label_6h_wind_kmh", "label_12h_wind_kmh",
                  "label_freezing_level_m", "label_precip_type"]
    mask = labels_df[label_cols].notna().any(axis=1)
    df = labels_df[mask].copy()

    if df.empty:
        return 0

    # Replace NaN/NaT with None for PostgreSQL
    df = df.where(pd.notna(df), None)
    # Explicitly fix object columns (NaN in object dtype can serialize as "nan")
    for col in df.select_dtypes(include=["object", "string"]).columns:
        df[col] = df[col].where(df[col].notna(), None)

    total = 0
    batch_size = 2000
    records = df.to_dict("records")

    # Ensure NaN floats become None in dicts
    for rec in records:
        for k, v in rec.items():
            if isinstance(v, float) and np.isnan(v):
                rec[k] = None

    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        stmt = pg_insert(TrainingLabel.__table__).values(batch)
        stmt = stmt.on_conflict_do_nothing(index_elements=["location_id", "target_time"])
        db.execute(stmt)
        db.commit()
        total += len(batch)
        if (i + batch_size) % 10000 < batch_size:
            log.info("Inserted %d / %d label rows", total, len(records))

    return total


def main():
    parser = argparse.ArgumentParser(description="Generate training labels from observations")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2022, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.end is None:
        args.end = date.today()

    log.info("Generating labels from %s to %s", args.start, args.end)

    db = SessionLocal()
    try:
        log.info("Loading Open-Meteo observations...")
        obs_df = load_observations(db, args.start, args.end)
        log.info("Loaded %d observation rows", len(obs_df))

        log.info("Loading ECCC base temperature...")
        eccc_temp_df = load_base_eccc_temperature(db, args.start, args.end)
        log.info("Loaded %d ECCC temperature rows", len(eccc_temp_df))

        log.info("Computing labels...")
        labels_df = compute_labels(obs_df, eccc_temp_df)
        log.info("Computed %d label rows", len(labels_df))

        log.info("Inserting into database...")
        inserted = insert_labels(db, labels_df)
        log.info("Inserted %d label rows", inserted)
    finally:
        db.close()

    log.info("Done.")


if __name__ == "__main__":
    main()

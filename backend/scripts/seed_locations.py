"""Seed the locations table with Whistler Blackcomb elevation bands."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.database import SessionLocal
from app.models.location import Location

LOCATIONS = [
    {"name": "base", "latitude": 50.1145, "longitude": -122.9540, "elevation_m": 675},
    {"name": "mid", "latitude": 50.1070, "longitude": -122.9480, "elevation_m": 1500},
    {"name": "alpine", "latitude": 50.0990, "longitude": -122.9420, "elevation_m": 2200},
]


def seed():
    db = SessionLocal()
    try:
        for loc in LOCATIONS:
            exists = db.execute(
                select(Location).where(Location.name == loc["name"])
            ).scalar_one_or_none()
            if not exists:
                db.add(Location(**loc))
                print(f"Added location: {loc['name']}")
            else:
                print(f"Location already exists: {loc['name']}")
        db.commit()
        print("Seed complete.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()

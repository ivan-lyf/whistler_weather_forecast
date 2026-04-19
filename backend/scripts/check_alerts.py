"""Check alert rules against latest predictions and send SMS notifications.

Usage:
    python scripts/check_alerts.py [--verbose]
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.alert_service import check_drift_alerts, check_weather_alerts
from app.database import SessionLocal

log = logging.getLogger("check_alerts")


def main():
    parser = argparse.ArgumentParser(description="Check and send weather alerts")
    parser.add_argument("--drift-alerts", type=str, default=None,
                        help="JSON string of drift alerts (from evaluate_live)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    db = SessionLocal()
    try:
        log.info("Checking weather alerts...")
        weather_count = check_weather_alerts(db)

        drift_count = 0
        if args.drift_alerts:
            import json
            try:
                drift_data = json.loads(args.drift_alerts)
                if drift_data:
                    log.info("Checking drift alerts...")
                    drift_count = check_drift_alerts(db, drift_data)
            except json.JSONDecodeError:
                log.warning("Could not parse drift alerts JSON")

        log.info("Done. Weather alerts: %d, Drift alerts: %d", weather_count, drift_count)
    finally:
        db.close()


if __name__ == "__main__":
    main()

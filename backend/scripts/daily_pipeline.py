"""Daily pipeline: ingest latest data, fetch live forecast, generate predictions.

Run via cron or scheduler:
    Every 6 hours:  0 */6 * * * cd /app/backend && python scripts/daily_pipeline.py
    Or daily:       0 8 * * * cd /app/backend && python scripts/daily_pipeline.py

Steps:
    1. Ingest recent observations (ECCC + Open-Meteo, last 7 days)
    2. Ingest archived forecast history (last 7 days)
    3. Fetch latest live GFS forecast (next 7 days)
    4. Generate labels for new observation data
    5. Generate and store ML predictions from live forecast
"""

import logging
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger("daily_pipeline")

BACKEND_DIR = Path(__file__).resolve().parent.parent


def run_step(name: str, cmd: list[str]) -> bool:
    log.info("=== %s ===", name)
    start = time.time()
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(BACKEND_DIR),
        env={**__import__("os").environ, "ENV": "production"},
    )
    elapsed = time.time() - start

    if result.returncode != 0:
        log.error("%s FAILED (%.1fs):\n%s", name, elapsed, result.stderr[-500:] if result.stderr else "no stderr")
        return False

    log.info("%s OK (%.1fs)", name, elapsed)
    for line in (result.stdout or "").strip().split("\n")[-3:]:
        if line.strip():
            log.info("  %s", line.strip())
    return True


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    yesterday = date.today() - timedelta(days=1)
    week_ago = date.today() - timedelta(days=7)
    python = sys.executable

    log.info("=== Daily Pipeline Start ===")
    ok = True

    # 1. Ingest observations (last 7 days to catch late-arriving data)
    ok &= run_step("Ingest ECCC observations", [
        python, "scripts/ingest_observations.py", "eccc",
        "--start", week_ago.isoformat(), "--end", yesterday.isoformat(),
    ])

    ok &= run_step("Ingest Open-Meteo observations", [
        python, "scripts/ingest_observations.py", "meteo",
        "--start", week_ago.isoformat(), "--end", yesterday.isoformat(),
    ])

    # 2. Ingest archived forecast history
    ok &= run_step("Ingest archived forecasts", [
        python, "scripts/ingest_forecasts.py", "historical",
        "--start", week_ago.isoformat(), "--end", yesterday.isoformat(),
    ])

    # 3. Fetch latest live GFS forecast (next 7 days)
    ok &= run_step("Fetch live GFS forecast", [
        python, "scripts/ingest_live_forecast.py", "--forecast-days", "7",
    ])

    # 4. Generate labels for new observation data
    ok &= run_step("Generate labels", [
        python, "scripts/generate_labels.py",
        "--start", week_ago.isoformat(), "--end", yesterday.isoformat(),
    ])

    # 5. Generate predictions from the live forecast
    ok &= run_step("Generate predictions", [
        python, "scripts/generate_predictions.py", "--hours", "168",
    ])

    # 6. Check weather alerts (compare rules against new predictions)
    ok &= run_step("Check weather alerts", [
        python, "scripts/check_alerts.py",
    ])

    # 7. Evaluate past predictions against observations
    ok &= run_step("Evaluate predictions", [
        python, "scripts/evaluate_live.py", "--days", "7",
    ])

    if ok:
        log.info("=== Daily Pipeline Complete (all steps OK) ===")
    else:
        log.error("=== Daily Pipeline Complete (with errors) ===")
        sys.exit(1)


if __name__ == "__main__":
    main()

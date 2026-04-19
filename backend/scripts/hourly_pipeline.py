"""Lightweight hourly pipeline: fetch latest forecast, generate predictions, check alerts.

Runs every hour via cron:
    0 * * * * cd /app/backend && python scripts/hourly_pipeline.py

Only does what's needed for fresh predictions — no historical ingestion, no labels, no evaluation.
Those run in the daily pipeline instead.
"""

import logging
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger("hourly_pipeline")

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
        log.error("%s FAILED (%.1fs):\n%s", name, elapsed, result.stderr[-300:] if result.stderr else "no stderr")
        return False

    log.info("%s OK (%.1fs)", name, elapsed)
    for line in (result.stdout or "").strip().split("\n")[-2:]:
        if line.strip():
            log.info("  %s", line.strip())
    return True


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    python = sys.executable
    log.info("=== Hourly Pipeline Start ===")
    ok = True

    # 1. Fetch latest GFS + ECMWF forecast
    ok &= run_step("Fetch live forecast", [
        python, "scripts/ingest_live_forecast.py", "--forecast-days", "3",
    ])

    # 2. Generate predictions from latest run
    ok &= run_step("Generate predictions", [
        python, "scripts/generate_predictions.py", "--hours", "72",
    ])

    # 3. Check weather alerts
    ok &= run_step("Check alerts", [
        python, "scripts/check_alerts.py",
    ])

    if ok:
        log.info("=== Hourly Pipeline Complete ===")
    else:
        log.error("=== Hourly Pipeline Complete (with errors) ===")
        sys.exit(1)


if __name__ == "__main__":
    main()

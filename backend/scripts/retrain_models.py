"""Retrain all models with latest data. Run weekly or monthly.

Usage:
    python scripts/retrain_models.py [--targets all]
"""

import logging
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger("retrain")

BACKEND_DIR = Path(__file__).resolve().parent.parent
TARGETS = ["snowfall_24h", "wind_6h", "wind_12h", "freezing_level", "precip_type"]


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log.info("Retraining all models...")
    python = sys.executable
    results = {}

    for target in TARGETS:
        log.info("=== Training: %s ===", target)
        start = time.time()
        result = subprocess.run(
            [python, "scripts/train_model.py", "--target", target],
            capture_output=True, text=True, cwd=str(BACKEND_DIR),
            env={**__import__("os").environ, "ENV": "production"},
        )
        elapsed = time.time() - start

        if result.returncode == 0:
            log.info("%s OK (%.1fs)", target, elapsed)
            # Extract test metrics from output
            for line in (result.stdout or "").split("\n"):
                if "test" in line.lower() and ("mae" in line.lower() or "acc" in line.lower()):
                    log.info("  %s", line.strip())
            results[target] = "ok"
        else:
            log.error("%s FAILED (%.1fs)", target, elapsed)
            log.error("  %s", (result.stderr or "")[-300:])
            results[target] = "failed"

    log.info("=== Retrain Summary ===")
    for target, status in results.items():
        log.info("  %-20s %s", target, status.upper())

    if any(v == "failed" for v in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()

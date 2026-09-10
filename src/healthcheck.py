"""Docker health probe: require a recently completed scanner job."""

import os
from pathlib import Path
import time

HEALTH_PATH = Path("/tmp/mexc-scanner-health")


def is_healthy():
    try:
        max_age = max(180, int(os.getenv("SCRAPE_INTERVAL", "60")) * 3)
        return 0 <= time.time() - HEALTH_PATH.stat().st_mtime <= max_age
    except (OSError, ValueError):
        return False


if __name__ == "__main__":
    raise SystemExit(0 if is_healthy() else 1)

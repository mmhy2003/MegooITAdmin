"""python -m app.collector.health: the collector's healthcheck. The supervisor touches the heartbeat after each read of
servers, every 10 seconds, so a heartbeat older than 30 seconds means the collector is stuck or cannot read them."""

import sys
import time
from pathlib import Path

from app.core.config import get_settings

MAX_AGE = 30.0


def healthy(path: Path, now: float | None = None) -> bool:
    """Whether the heartbeat exists and is under MAX_AGE seconds old."""
    try:
        touched = path.stat().st_mtime
    except OSError:
        return False
    return (time.time() if now is None else now) - touched < MAX_AGE


def main() -> int:
    return 0 if healthy(Path(get_settings().collector_heartbeat_file)) else 1


if __name__ == "__main__":
    sys.exit(main())

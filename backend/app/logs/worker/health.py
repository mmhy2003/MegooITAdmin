"""python -m app.logs.worker.health: the logs worker's healthcheck. The hub touches the heartbeat every second, so a
heartbeat older than 30 seconds means the worker is stuck or has lost Valkey."""

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
    return 0 if healthy(Path(get_settings().logs_heartbeat_file)) else 1


if __name__ == "__main__":
    sys.exit(main())

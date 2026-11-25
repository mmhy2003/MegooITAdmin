"""The slow checks the collector runs on their own intervals, each a short script on a second channel of the stream's
SSH connection:
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.checks.models import Kind
from app.collector.checks.parse import CheckResult


@dataclass(frozen=True)
class Check:
    kind: Kind
    every: float  # seconds between two runs
    timeout: float  # seconds one run may take
    script: bytes
    parse: Callable[[list[bytes]], CheckResult]
    server_name: bool = False  # sends the server's host name as $1


def script_of(kind: str) -> bytes:
    """The script checks/<kind>.sh next to this file."""
    return Path(__file__).with_name(f"{kind}.sh").read_bytes()


CHECKS: tuple[Check, ...] = ()

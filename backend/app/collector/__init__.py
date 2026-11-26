"""The metrics collector (python -m app.collector): one SSH stream per server, each sample published on Valkey and
written to metrics. Beside each stream it also runs the server's slow checks on their own intervals. Run one collector:
a second one would publish every sample twice."""

from functools import cache
from pathlib import Path

SCRIPT = Path(__file__).with_name("script.sh")


@cache
def script() -> bytes:
    return SCRIPT.read_bytes()

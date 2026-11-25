"""A check's output read as a status and a bounded result (the protocol R3).

Line 1 is a JSON status line: {"status":"ok"}, {"status":"not_available"} or {"status":"denied"}. Only "ok" is
followed by a body, which the check's parser turns into its result. The server's account writes this output, so it is
bounded and never logged: anything unexpected is the status "failed".
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.checks.models import Status
from app.collector.parse import CONTROL
from app.metrics.samples import Reading
from app.ssh.client import ScriptResult

MAX_OUTPUT = 1024 * 1024
MAX_LINE = 64 * 1024
MAX_NAME = 255

_FIRST: tuple[Status, ...] = ("ok", "not_available", "denied")


class NotAvailable(Exception):
    """A parser raises it: the tool cannot answer on this server."""


class CheckResult(BaseModel):
    """What a check found. Each kind adds its fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    def data(self) -> dict[str, Any]:
        """What server_checks keeps."""
        return self.model_dump(mode="json")

    def readings(self, now: datetime) -> tuple[Reading, ...]:
        """The numbers sent to metrics."""
        return ()


@dataclass(frozen=True)
class Outcome:
    status: Status
    result: CheckResult | None = None  # set only when status == "ok"


def clean(text: str) -> str | None:
    """The text, or None when it is longer than MAX_NAME or holds a control character."""
    if len(text) > MAX_NAME or CONTROL.search(text):
        return None
    return text


def _status(line: bytes) -> Status | None:
    try:
        first = json.loads(line)
    except ValueError:
        return None
    if not isinstance(first, dict) or first.keys() != {"status"} or first["status"] not in _FIRST:
        return None
    return first["status"]


def read(parser: Callable[[list[bytes]], CheckResult], result: ScriptResult) -> Outcome:
    """The outcome of one run of a check. Never raises for anything the output holds."""
    if result.truncated or result.exit_status != 0:
        return Outcome("failed")
    lines = result.output.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    if not lines or any(len(line) > MAX_LINE for line in lines):
        return Outcome("failed")
    status = _status(lines[0])
    if status is None:
        return Outcome("failed")
    if status != "ok":
        return Outcome(status)
    try:
        return Outcome("ok", parser(lines[1:]))
    except NotAvailable:
        return Outcome("not_available")
    except ValueError:
        return Outcome("failed")

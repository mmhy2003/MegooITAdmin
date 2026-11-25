"""A check's output read as a status and a bounded result (the protocol R3).

Line 1 is a JSON status line: {"status":"ok"}, {"status":"not_available"} or {"status":"denied"}. Only "ok" is
followed by a body, which the check's parser turns into its result. The server's account writes this output, so it is
bounded and never logged: anything unexpected is the status "failed".
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.checks.models import CONTAINER_STATES, SeenContainer, Status
from app.collector.parse import CONTROL
from app.metrics.samples import Reading
from app.ssh.client import ScriptResult

MAX_OUTPUT = 1024 * 1024
MAX_LINE = 64 * 1024
MAX_NAME = 255
MAX_CONTAINERS = 500

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


class ContainersResult(CheckResult):
    containers: tuple[SeenContainer, ...]
    total: int
    running: int
    not_running: int

    def data(self) -> dict[str, Any]:
        # The containers have a table of their own.
        return self.model_dump(mode="json", exclude={"containers"})

    def readings(self, now: datetime) -> tuple[Reading, ...]:
        return (
            Reading(metric="containers.running", value=self.running),
            Reading(metric="containers.not_running", value=self.not_running),
        )


_CONTAINER_ID = re.compile(r"[0-9a-f]{12,64}")
_PROJECT = re.compile(r"(?:^|,)com\.docker\.compose\.project=([A-Za-z0-9_.-]{1,255})(?:,|$)")
_SERVICE = re.compile(r"(?:^|,)com\.docker\.compose\.service=([A-Za-z0-9_.-]{1,255})(?:,|$)")


def _label(pattern: re.Pattern[str], labels: object) -> str | None:
    found = pattern.search(labels) if isinstance(labels, str) else None
    return found.group(1) if found else None


def _seen(row: dict[str, Any]) -> SeenContainer | None:
    container_id, names, image, state = row.get("ID"), row.get("Names"), row.get("Image"), row.get("State")
    if not isinstance(container_id, str) or not _CONTAINER_ID.fullmatch(container_id):
        return None
    name = clean(names.split(",")[0]) if isinstance(names, str) else None
    image = clean(image) if isinstance(image, str) else None
    if not name or not image:
        return None
    status = row.get("Status")
    return SeenContainer(
        container_id=container_id,
        name=name,
        image=image,
        compose_project=_label(_PROJECT, row.get("Labels")),
        compose_service=_label(_SERVICE, row.get("Labels")),
        state=state.lower() if isinstance(state, str) and state.lower() in CONTAINER_STATES else "unknown",
        status=(clean(status) if isinstance(status, str) else None) or "",
    )


def containers(lines: list[bytes]) -> ContainersResult:
    """docker ps --all --no-trunc --format '{{json .}}': one JSON object per container."""
    kept: list[SeenContainer] = []
    total = running = 0
    for line in lines:
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("a line of docker ps is not an object")
        if not isinstance(row.get("State"), str):
            continue
        total += 1
        running += row["State"].lower() == "running"
        seen = _seen(row)
        if seen is not None and len(kept) < MAX_CONTAINERS:
            kept.append(seen)
    return ContainersResult(containers=tuple(kept), total=total, running=running, not_running=total - running)

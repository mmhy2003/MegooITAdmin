"""Running the slow checks of a server, and recording what each run found."""

import asyncio
import ipaddress
import logging
import random
import re
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.checks.models import Kind
from app.checks.store import replace_containers, write_check
from app.collector.checks import Check
from app.collector.checks.parse import MAX_OUTPUT, ContainersResult, Outcome, read
from app.collector.state import FOREIGN_KEY_VIOLATION
from app.collector.throttle import Throttle
from app.collector.writer import Writer
from app.metrics.samples import Sample
from app.ssh import client

if TYPE_CHECKING:
    from app.collector.stream import Publisher, Target

logger = logging.getLogger(__name__)
FIRST_DELAY = 10.0  # the first round starts at a random point of this many seconds, so servers do not run in step
HOST_NAME = re.compile(r"[A-Za-z0-9.-]{1,253}")
_bugs = Throttle()


class Timetable:
    """When each check is due next. Every check is due at one random start; then each is due its interval after it
    last started."""

    def __init__(
        self, checks: Sequence[Check], *, first_delay: float = FIRST_DELAY, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.checks = tuple(checks)
        start = clock() + random.uniform(0, first_delay)
        self._due = {check.kind: start for check in self.checks}

    def next(self) -> tuple[Check, float]:
        """The earliest due check (ties: registry order) and its due time."""
        _, check = min(enumerate(self.checks), key=lambda item: (self._due[item[1].kind], item[0]))
        return check, self._due[check.kind]

    def ran(self, kind: Kind, started: float) -> None:
        every = next(check.every for check in self.checks if check.kind == kind)
        self._due[kind] = started + every


def server_name(address: str) -> str | None:
    """The address as a host name, lowercased, or None when it is an IP address or not a host name."""
    try:
        ipaddress.ip_address(address)
    except ValueError:
        pass
    else:
        return None
    if HOST_NAME.fullmatch(address) and any(char.isalpha() for char in address):
        return address.lower()
    return None


async def run_check(conn: client.Connection, check: Check, address: str) -> Outcome:
    """Runs one check on a channel of its own. Never raises, except CancelledError."""
    name = server_name(address) if check.server_name else None
    args = (name,) if name is not None else ()
    try:
        result = await client.run_script(conn, check.script, args, timeout=check.timeout, max_output=MAX_OUTPUT)
        return read(check.parse, result)
    except client.ScriptTimeout:
        return Outcome("timeout")
    except client.SshFailure:
        return Outcome("failed")
    except Exception:
        # A bug: the stream goes on, and the next run tries again.
        if _bugs():
            logger.exception("The %s check failed unexpectedly", check.kind)
        return Outcome("failed")


async def run_checks(conn: client.Connection, target: "Target", timetable: Timetable, recorder: "Recorder") -> None:
    """Runs the checks one at a time, each when it is due, and records each outcome. Loops forever."""
    while True:
        check, due = timetable.next()
        await asyncio.sleep(max(0.0, due - time.monotonic()))
        started = time.monotonic()
        outcome = await run_check(conn, check, target.address)
        timetable.ran(check.kind, started)
        await recorder.record(target.server_id, check.kind, outcome, datetime.now(UTC))


class Recorder:
    """Writes a check's row (and a listing's containers) and sends its numbers as metrics. Never raises."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], publisher: "Publisher", writer: Writer) -> None:
        self.sessions, self.publisher, self.writer = sessions, publisher, writer
        self._warn = Throttle()

    async def record(self, server_id: UUID, kind: Kind, outcome: Outcome, at: datetime) -> None:
        result = outcome.result if outcome.status == "ok" else None
        await self._write(server_id, kind, outcome, at)
        if result is None:
            return
        readings = result.readings(at)
        if readings:
            # The writer keeps its own buffer, so the numbers go even when the row could not be written.
            sample = Sample(time=at, server_id=server_id, readings=readings)
            await self.publisher.publish(sample)
            self.writer.add(sample)

    async def _write(self, server_id: UUID, kind: Kind, outcome: Outcome, at: datetime) -> None:
        result = outcome.result if outcome.status == "ok" else None
        try:
            async with self.sessions() as session:
                data = result.data() if result is not None else None
                await write_check(session, server_id, kind, outcome.status, checked_at=at, data=data)
                if kind == "containers" and isinstance(result, ContainersResult):
                    # A failed listing leaves the containers as they were last seen.
                    await replace_containers(session, server_id, result.containers, seen_at=at)
                await session.commit()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == FOREIGN_KEY_VIOLATION:
                return  # the server was removed since the collector read it
            self._warn_failed(server_id, exc)
        except (SQLAlchemyError, OSError) as exc:
            # No retry queue: the next run writes the row again.
            self._warn_failed(server_id, exc)

    def _warn_failed(self, server_id: UUID, exc: Exception) -> None:
        if self._warn():
            logger.warning(
                "Could not write a check result of server %s, it is written again at its next run: %s",
                server_id,
                type(exc).__name__,
            )

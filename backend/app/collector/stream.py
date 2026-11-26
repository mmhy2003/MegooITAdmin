"""One server's stream: sign in through open_connection, run the loop on one channel, turn each line into a Sample,
publish it and buffer it for the writer. A closed channel, or no sample for no_sample_after seconds, closes the
connection; the next try waits 1, 2, 4 ... up to 60 seconds with jitter, and a sample resets the wait.

With a recorder, the slow checks run on a second channel of the same connection, each when it is due. Their failures
never end the session: only the loop decides that."""

import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from valkey.asyncio import Valkey
from valkey.exceptions import ValkeyError

from app.audit import Actor
from app.collector import compute, script
from app.collector.checks import CHECKS, Check
from app.collector.checks.runner import FIRST_DELAY, Recorder, Timetable, run_checks
from app.collector.parse import Lines, parse
from app.collector.state import StatusBook
from app.collector.throttle import Throttle
from app.collector.writer import Writer
from app.inventory.connection import ConnectionRefused, open_connection
from app.inventory.models import Server
from app.metrics.fanout import publish
from app.metrics.samples import Sample
from app.ssh import client
from app.ssh.keys import KeyFileError

if TYPE_CHECKING:  # the book imports the supervisor, which imports this module
    from app.collector.alerts.book import AlertBook

logger = logging.getLogger(__name__)
ACTOR = Actor.system("collector")
MAX_SIGN_INS = 20


@dataclass(frozen=True)
class Timings:
    no_sample_after: float = 30.0
    backoff_first: float = 1.0
    backoff_max: float = 60.0
    jitter: float = 0.2

    def wait(self, delay: float) -> float:
        return delay * random.uniform(1 - self.jitter, 1 + self.jitter)


@dataclass(frozen=True)
class Target:
    """What a stream needs of its server. Any change restarts the stream."""

    server_id: UUID
    address: str
    port: int
    username: str
    host_key: str
    interval: int

    @classmethod
    def of(cls, server: Server) -> "Target":
        return cls(
            server.id,
            server.address,
            server.port,
            server.connection_settings["username"],
            server.host_key,
            server.metrics_interval_seconds,
        )

    def server(self) -> Server:
        """A transient Server for open_connection, which reads the row again only to flag a changed key."""
        return Server(
            id=self.server_id,
            os="linux",
            address=self.address,
            port=self.port,
            host_key=self.host_key,
            host_key_changed_at=None,
            connection_settings={"username": self.username},
        )


class Publisher:
    """Publishes on Valkey, never raises: with Valkey down the samples are still written."""

    def __init__(self, valkey: Valkey | None, timeout: float = 1.0) -> None:
        self.valkey, self.timeout, self._warned = valkey, timeout, Throttle()

    async def publish(self, sample: Sample) -> None:
        if self.valkey is None:
            return
        try:
            await asyncio.wait_for(publish(self.valkey, sample), self.timeout)
        except (ValkeyError, OSError) as error:  # TimeoutError is an OSError
            if self._warned():
                logger.warning("Could not publish samples on Valkey: %s", error)


class Stream:
    def __init__(
        self,
        target: Target,
        *,
        publisher: Publisher,
        writer: Writer,
        status: StatusBook,
        timings: Timings = Timings(),
        sign_ins: asyncio.Semaphore | None = None,
        recorder: Recorder | None = None,
        checks: Sequence[Check] = CHECKS,
        first_delay: float = FIRST_DELAY,
        clock: Callable[[], float] = time.monotonic,
        alerts: "AlertBook | None" = None,
    ) -> None:
        self.target, self.publisher, self.writer, self.status, self.timings = target, publisher, writer, status, timings
        self.sign_ins = sign_ins or asyncio.Semaphore(MAX_SIGN_INS)
        self.clock = clock
        self.recorder = recorder  # None: no check runs
        self.alerts = alerts  # None: no rule is checked
        # On the stream, not the session: a reconnect does not run a check again before its interval.
        self.timetable = Timetable(checks, first_delay=first_delay, clock=clock)
        self.failure: str | None = None  # the reason of the last failure, None after a sample
        self.last_sample = clock()  # monotonic; the task's start counts as one
        self.last_sample_at: datetime | None = None
        self.samples = 0
        self.bad_lines = 0
        self._bad, self._key = Throttle(), Throttle()

    async def run(self) -> None:
        """Streams until cancelled, or until the server cannot be tried any more (changed host key)."""
        watch = asyncio.create_task(self._watch())
        try:
            delay = self.timings.backoff_first
            while True:
                before = self.samples
                try:
                    await self._session()
                except client.HostKeyChanged:
                    await self.status.set(self.target.server_id, "not_monitored", "host_key_changed")
                    return
                except ConnectionRefused as refused:
                    await self.status.set(self.target.server_id, "not_monitored", refused.detail)
                    return
                if self.samples > before:
                    delay = self.timings.backoff_first
                await asyncio.sleep(self.timings.wait(delay))
                delay = min(delay * 2, self.timings.backoff_max)
        finally:
            watch.cancel()

    async def _session(self) -> None:
        try:
            async with AsyncExitStack() as stack:
                async with self.sign_ins:  # at most MAX_SIGN_INS sign-ins at once
                    conn = await stack.enter_async_context(
                        open_connection(self.target.server(), actor=ACTOR, source=None)
                    )
                    chunks = await stack.enter_async_context(
                        client.script_output(conn, script(), self.target.interval)
                    )
                if self.recorder is not None:
                    # The stack closes in reverse, so the checks stop before the channel and the connection.
                    checks = asyncio.create_task(run_checks(conn, self.target, self.timetable, self.recorder))
                    stack.push_async_callback(_stop_task, checks)
                await self._read(chunks)
        except client.HostKeyChanged:
            raise
        except client.SshFailure as failure:
            self.failure = failure.reason
        except KeyFileError as error:
            self.failure = "ssh_error"
            if self._key():
                logger.error("%s", error)

    async def _read(self, chunks: AsyncIterator[bytes]) -> None:
        lines, previous, got = Lines(), None, False
        loop = asyncio.get_running_loop()
        try:
            async with asyncio.timeout(self.timings.no_sample_after) as deadline:
                async for chunk in chunks:
                    skipped = lines.too_long
                    for line in lines.feed(chunk):
                        try:
                            raw = parse(line)
                        except ValueError:
                            self._bad_line()
                            continue
                        sample = Sample(
                            time=datetime.now(UTC),
                            server_id=self.target.server_id,
                            readings=compute.readings(previous, raw),
                        )
                        previous = raw
                        deadline.reschedule(loop.time() + self.timings.no_sample_after)
                        await self._got(sample, compute.cores(raw))
                        got = True
                    for _ in range(lines.too_long - skipped):
                        self._bad_line()
        except TimeoutError:
            self.failure = "no_samples"
            return
        # The channel ended. Without a single sample, the loop could not run there.
        self.failure = None if got else "ssh_error"

    def _bad_line(self) -> None:
        # The line's text is never logged: it comes from the server.
        self.bad_lines += 1
        if self._bad():
            logger.warning(
                "Dropped %d lines from server %s that were not samples", self.bad_lines, self.target.server_id
            )

    async def _got(self, sample: Sample, cores: int) -> None:
        self.samples += 1
        self.last_sample, self.last_sample_at, self.failure = self.clock(), sample.time, None
        await self.publisher.publish(sample)
        self.writer.add(sample)
        if self.alerts is not None:
            await self.alerts.observe(sample, cores)
        await self.status.set(self.target.server_id, "reachable", None, last_sample_at=sample.time)

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(self.timings.no_sample_after / 4)
            if self.clock() - self.last_sample >= self.timings.no_sample_after:
                await self.status.set(
                    self.target.server_id,
                    "unreachable",
                    self.failure or "no_samples",
                    last_sample_at=self.last_sample_at,
                )


async def _stop_task(task: asyncio.Task[None]) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError, Exception):
        await task

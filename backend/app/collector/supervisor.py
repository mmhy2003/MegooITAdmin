"""Reads servers every 10 seconds and keeps one stream per server that can be tried. A server that cannot be tried
gets not_monitored and no connection attempt. With a recorder, every stream also runs its server's slow checks."""

import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.collector.checks import CHECKS, Check
from app.collector.checks.runner import FIRST_DELAY, Recorder
from app.collector.state import StatusBook
from app.collector.stream import MAX_SIGN_INS, Publisher, Stream, Target, Timings
from app.collector.throttle import Throttle
from app.collector.writer import Writer
from app.inventory.models import Server

logger = logging.getLogger(__name__)

POLL_EVERY = 10.0


def refusal_of(server: Server) -> str | None:
    """Why the collector does not try this server, or None when it does."""
    if server.os != "linux":
        return "not_an_ssh_server"
    if server.host_key is None:
        return "host_key_not_pinned"
    if server.host_key_changed_at is not None:
        return "host_key_changed"
    return None


class Supervisor:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        publisher: Publisher,
        writer: Writer,
        status: StatusBook,
        timings: Timings = Timings(),
        poll_every: float = POLL_EVERY,
        heartbeat: Path | None = None,
        max_sign_ins: int = MAX_SIGN_INS,
        recorder: Recorder | None = None,
        checks: Sequence[Check] = CHECKS,
        first_delay: float = FIRST_DELAY,
    ) -> None:
        self.sessions, self.publisher, self.writer, self.status = sessions, publisher, writer, status
        self.timings, self.poll_every, self.heartbeat = timings, poll_every, heartbeat
        self.sign_ins = asyncio.Semaphore(max_sign_ins)  # shared by every stream
        self.recorder, self.checks, self.first_delay = recorder, checks, first_delay
        self._streams: dict[UUID, tuple[Stream, asyncio.Task[None]]] = {}
        self._stopping: set[asyncio.Task[None]] = set()
        self._warned = Throttle()

    @property
    def targets(self) -> dict[UUID, Target]:
        """The servers streaming now."""
        return {server_id: stream.target for server_id, (stream, task) in self._streams.items() if not task.done()}

    async def poll(self) -> None:
        """Starts, keeps, restarts or stops each server's stream after the servers table. Raises on a database
        error."""
        # A stream that returned by itself (a changed host key) flagged its row first, so this read sees the flag.
        ended = {server_id for server_id, (_, task) in self._streams.items() if task.done()}
        async with self.sessions() as session:
            rows = (await session.scalars(select(Server))).all()
        for row in rows:
            refusal = refusal_of(row)
            if refusal is not None:
                self._stop(row.id)
                await self.status.set(row.id, "not_monitored", refusal)
                continue
            target = Target.of(row)
            current = self._streams.get(row.id)
            if current is not None and current[0].target == target:
                task = current[1]
                if row.id not in ended:
                    # Running, or it returned after this poll read the rows: the next poll sees why.
                    continue
                if not task.cancelled() and task.exception() is not None:
                    logger.warning("The stream of %s stopped: %r", row.id, task.exception())
            self._stop(row.id)
            self._start(target)
        ids = {row.id for row in rows}
        for server_id in set(self._streams) - ids:
            self._stop(server_id)
        for server_id in self.status.known_ids() - ids:
            self.status.forget(server_id)
        await self.status.retry()
        if self.heartbeat is not None:
            self.heartbeat.touch()

    def _start(self, target: Target) -> None:
        stream = Stream(
            target,
            publisher=self.publisher,
            writer=self.writer,
            status=self.status,
            timings=self.timings,
            sign_ins=self.sign_ins,
            recorder=self.recorder,
            checks=self.checks,
            first_delay=self.first_delay,
        )
        self._streams[target.server_id] = (stream, asyncio.create_task(stream.run()))

    def _stop(self, server_id: UUID) -> None:
        current = self._streams.pop(server_id, None)
        if current is None:
            return
        task = current[1]
        task.cancel()
        self._stopping.add(task)
        task.add_done_callback(self._stopping.discard)

    async def run(self) -> None:
        while True:
            try:
                await self.poll()
            except (SQLAlchemyError, OSError) as error:
                if self._warned():
                    logger.warning("Could not read the servers, will retry: %s", type(error).__name__)
            except Exception:
                # A bug: the heartbeat goes stale, so the healthcheck shows it, and the next poll tries again.
                logger.exception("Could not follow the servers, will retry")
            await asyncio.sleep(self.poll_every)

    async def stop(self) -> None:
        """Stops every stream and waits until they have closed their connections."""
        for server_id in list(self._streams):
            self._stop(server_id)
        await asyncio.gather(*self._stopping, return_exceptions=True)

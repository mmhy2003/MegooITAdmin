"""The logs worker's hub: it answers the sockets' open requests and keeps one running source per key.

Anything on the core network can publish on Valkey, so each request is checked again in the database: the server, a
file's path against its group's patterns, a container. A source already running is shared: the new viewer gets the
lines it holds. Requests are handled one at a time, in order, so two requests for one new source start one channel.
Every count_every seconds the hub asks Valkey how many subscribers each source's channel has; a source without one
for close_after seconds stops. Every recheck_every seconds a source whose server is gone, or a file whose pattern is
gone, ends. The hub says it is alive on WORKER with its run id, so sockets see a restart."""

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from valkey.asyncio import Valkey

from app.checks.models import Container
from app.inventory.models import Server
from app.logs.allowlist import matches, patterns_of
from app.logs.protocol import (
    REQUESTS,
    WORKER,
    Alive,
    Opened,
    OpenRequest,
    Refused,
    encode,
    source_channel,
    viewer_channel,
)
from app.logs.sources import FileSource, Source, source_key
from app.logs.worker.links import Links
from app.logs.worker.source import Limits, RunningSource

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Timings:
    count_every: float = 1.0
    close_after: float = 5.0
    alive_every: float = 5.0
    recheck_every: float = 30.0


class Hub:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        valkey: Valkey,
        *,
        limits: Limits = Limits(),
        timings: Timings = Timings(),
        links: Links | None = None,
        run_id: str | None = None,
    ):
        self.run_id = run_id or uuid4().hex
        self.running: dict[str, RunningSource] = {}
        self._sessions = sessions
        self._valkey = valkey
        self._limits = limits
        self._timings = timings
        self._links = links or Links()

    async def run(self, heartbeat: Path | None = None) -> None:
        """Listens, counts, says it is alive and rechecks until cancelled. A Valkey error ends it."""
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(self._listen())
            tasks.create_task(self._count(heartbeat))
            tasks.create_task(self._alive())
            tasks.create_task(self._recheck())

    async def handle(self, request: OpenRequest) -> Opened | Refused:
        """Answers the request on the socket's viewer channel: opened with the lines the source holds, or refused."""
        source = request.source
        key = source_key(source)
        checked = await self._check(source)
        reason = checked if isinstance(checked, str) else None
        if isinstance(checked, Server) and key not in self.running:
            reason = self._start(key, source, checked)
        answer: Opened | Refused
        if reason is None:
            lines, last_seq = self.running[key].snapshot()
            answer = Opened(type="opened", request_id=request.request_id, key=key, run_id=self.run_id, lines=lines,
                            last_seq=last_seq)
        else:
            answer = Refused(type="refused", request_id=request.request_id, key=key, reason=reason)
        await self._valkey.publish(viewer_channel(request.socket_id), encode(answer))
        return answer

    async def stop(self) -> None:
        """Stops every running source and waits until their channels have closed."""
        stopping = list(self.running.values())
        self.running.clear()
        await asyncio.gather(*(running.stop() for running in stopping))

    async def _check(self, source: Source) -> Server | str:
        """The source's server when the source may open, after the database; otherwise why it may not."""
        async with self._sessions() as session:
            server = await session.get(Server, source.server_id)
            if server is None:
                return "not_found"
            if server.os != "linux":
                return "not_an_ssh_server"
            if server.host_key is None:
                return "host_key_not_pinned"
            if server.host_key_changed_at is not None:
                return "host_key_changed"
            if isinstance(source, FileSource):
                patterns = (await patterns_of(session, [server.server_group_id])).get(server.server_group_id, [])
                if not matches(source.path, patterns):
                    return "not_allowed"
            if source.kind == "container":
                row = await session.get(Container, (server.id, "docker", source.container_id))
                if row is None:
                    return "not_found"
        return server

    def _start(self, key: str, source: Source, server: Server) -> str | None:
        """Starts the source; too_many_sources when its server already runs the most it may."""
        if sum(running.server_id == server.id for running in self.running.values()) >= self._limits.sources_per_server:
            return "too_many_sources"
        running = RunningSource(key, source, server, links=self._links, valkey=self._valkey, limits=self._limits)
        self.running[key] = running
        running.start(self._ended)
        return None

    def _ended(self, running: RunningSource) -> None:
        if self.running.get(running.key) is running:
            del self.running[running.key]

    async def _listen(self) -> None:
        pubsub = self._valkey.pubsub()
        try:
            await pubsub.subscribe(REQUESTS)
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is None:
                    continue
                try:
                    request = OpenRequest.model_validate_json(message["data"])
                except ValidationError as error:
                    logger.warning("Skipped a bad open request: %s", error.errors(include_input=False))
                    continue
                await self.handle(request)
        finally:
            await pubsub.aclose()

    async def _count(self, heartbeat: Path | None) -> None:
        while True:
            if self.running:
                keys = list(self.running)
                counts = dict(await self._valkey.pubsub_numsub(*(source_channel(key) for key in keys)))
                now = time.monotonic()
                for key in keys:
                    running = self.running.get(key)
                    if running is None:
                        continue
                    if counts.get(source_channel(key).encode(), 0) > 0:
                        running.zero_since = None
                    elif running.zero_since is None:
                        running.zero_since = now
                    elif now - running.zero_since >= self._timings.close_after:
                        del self.running[key]
                        await running.stop()
            if heartbeat is not None:
                heartbeat.touch()
            await asyncio.sleep(self._timings.count_every)

    async def _alive(self) -> None:
        while True:
            await self._valkey.publish(WORKER, encode(Alive(type="alive", run_id=self.run_id)))
            await asyncio.sleep(self._timings.alive_every)

    async def _recheck(self) -> None:
        while True:
            await asyncio.sleep(self._timings.recheck_every)
            if self.running:
                await self._recheck_once()

    async def _recheck_once(self) -> None:
        """Ends the sources whose server is gone (not_found) and the files whose pattern is gone (not_allowed)."""
        checked = list(self.running.values())
        async with self._sessions() as session:
            ids = {running.server_id for running in checked}
            servers: dict[UUID, Server] = {
                server.id: server for server in await session.scalars(select(Server).where(Server.id.in_(ids)))
            }
            patterns = await patterns_of(session, {server.server_group_id for server in servers.values()})
        for running in checked:
            server = servers.get(running.server_id)
            if server is None:
                reason = "not_found"
            elif isinstance(running.source, FileSource) and not matches(
                running.source.path, patterns.get(server.server_group_id, [])
            ):
                reason = "not_allowed"
            else:
                continue
            if self.running.get(running.key) is running:
                del self.running[running.key]
                await running.end(reason)

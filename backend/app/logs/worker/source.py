"""One running source: its command on a channel of the server's shared connection, the lines read from it, the cap,
the last lines a new viewer gets first, and the publisher of what its viewers receive.

The reader cuts the output into lines, parses them and passes them through the cap. A kept line gets the next seq,
joins the backlog and waits in the batcher; a dropped line is counted there. The publisher sends what waits every
batch_every seconds, or at once when batch_lines lines wait, on the source's channel. When the command ends, what is
left goes out, then the end and its reason: how the command exited, or why the server refused or failed. Nothing is
stored: the backlog lives in this process only."""

import asyncio
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel
from valkey.asyncio import Valkey

from app.inventory.connection import ConnectionRefused
from app.inventory.models import Server
from app.logs.cap import Batcher, Cap
from app.logs.lines import MAX_JOURNAL_BYTES, MAX_LINE_BYTES, Splitter, line_message, parse
from app.logs.protocol import ON_SOURCE, Ended, encode, source_channel
from app.logs.sources import BACKLOG, NOT_READABLE, Source, command
from app.logs.worker.links import Links
from app.ssh import client


@dataclass(frozen=True)
class Limits:
    max_lines_per_second: int = 2000
    backlog: int = BACKLOG
    sources_per_server: int = 8
    batch_every: float = 0.1
    batch_lines: int = 500


DIAGNOSTICS = (b"sudo: ", b"megoo-ctl: ")  # container error lines that are not the container's


def ended_by(kind: str, exit: client.Exit) -> tuple[str, int | None]:
    """The reason and the status of an end, from how the command exited: 127 is a command the server lacks, a file
    script's NOT_READABLE a file megoo cannot read, and a container's sudo error a missing sudo rule."""
    if exit.status == 127:
        return "not_available", None
    if kind == "file" and exit.status == NOT_READABLE:
        return "not_readable", None
    if kind == "container" and any(line.startswith(b"sudo: ") for line in exit.errors.splitlines()):
        return "denied", None
    return "exited", exit.status


class RunningSource:
    def __init__(
        self,
        key: str,
        source: Source,
        server: Server,
        *,
        links: Links,
        valkey: Valkey,
        limits: Limits,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.key = key
        self.source = source
        self.server_id = server.id
        self.zero_since: float | None = None  # since when the source's channel has no subscriber
        self._server = server
        self._links = links
        self._valkey = valkey
        self._limits = limits
        self._channel = source_channel(key)
        self._cap = Cap(limits.max_lines_per_second, clock)
        self._batcher = Batcher(limits.batch_lines)
        self._backlog: deque[dict] = deque(maxlen=limits.backlog)
        self._seq = 0
        self._publishing = asyncio.Lock()  # one batch at a time, so they go out in order
        self._task: asyncio.Task[None] | None = None

    def snapshot(self) -> tuple[list[dict], int]:
        """The last limits.backlog kept line messages, and the last seq (0 before the first line)."""
        return list(self._backlog), self._seq

    def start(self, on_end: Callable[["RunningSource"], None]) -> None:
        """Runs the source; on_end gets it when it ends by itself, not when it is stopped."""
        self._task = asyncio.create_task(self._run(on_end))

    async def stop(self) -> None:
        """Cancels the source and waits for its channel to close; publishes nothing."""
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task

    async def end(self, reason: str) -> None:
        """Stops the source, then tells the viewers it ended for this reason: nothing of it follows the end."""
        await self.stop()
        await self._publish(Ended(type="ended", reason=reason))

    async def _run(self, on_end: Callable[["RunningSource"], None]) -> None:
        try:
            ended = await self._follow()
        except ConnectionRefused as refused:
            ended = Ended(type="ended", reason=refused.detail)
        except client.SshFailure as failure:
            ended = Ended(type="ended", reason=failure.reason)
        await self._flush()
        await self._publish(ended)
        on_end(self)

    async def _follow(self) -> Ended:
        """Reads the command's output until it ends, and tells how it ended."""
        async with self._links.use(self._server) as conn, client.follow(conn, command(self.source)) as followed:
            flusher = asyncio.create_task(self._flush_every())
            try:
                await self._read(followed)
            finally:
                # Under the lock the flusher sleeps or waits for it: cancelling it loses no batch it took.
                async with self._publishing:
                    flusher.cancel()
                with suppress(asyncio.CancelledError):
                    await flusher
        assert followed.exit is not None  # set when the iteration ended
        reason, status = ended_by(self.source.kind, followed.exit)
        return Ended(type="ended", reason=reason, status=status)

    async def _read(self, followed: client.Follower) -> None:
        kind = self.source.kind
        size = MAX_JOURNAL_BYTES if kind == "journal" else MAX_LINE_BYTES
        splitters = {"out": Splitter(size), "err": Splitter(size)}
        async for stream, chunk in followed:
            if stream == "err" and kind != "container":
                continue  # journalctl and tail say nothing a viewer needs on their error output
            self._take(splitters[stream].feed(chunk))
            if self._batcher.full:
                await self._flush()
        for splitter in splitters.values():
            self._take(splitter.rest())

    def _take(self, lines: list[tuple[bytes, bool]]) -> None:
        kind = self.source.kind
        read_at = datetime.now(UTC)
        for raw, cut in lines:
            if kind == "container" and raw.startswith(DIAGNOSTICS):
                continue
            if not self._cap.admit():
                self._batcher.drop()
                continue
            self._seq += 1
            message = line_message(parse(kind, raw, seq=self._seq, read_at=read_at, cut=cut))
            self._batcher.keep(message)
            self._backlog.append(message)

    async def _flush_every(self) -> None:
        while True:
            await asyncio.sleep(self._limits.batch_every)
            await self._flush()

    async def _flush(self) -> None:
        async with self._publishing:
            for message in self._batcher.take():
                await self._publish(ON_SOURCE.validate_python(message))

    async def _publish(self, message: BaseModel) -> None:
        await self._valkey.publish(self._channel, encode(message))

"""The logs worker's hub against the fake server and a real Valkey: it checks each open request again in the database,
shares one source between its viewers, refuses what it must, closes a source without subscribers, says it is alive,
and ends a source whose server or pattern went away."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, update

from app.core.valkey import valkey_client
from app.inventory.models import Server
from app.logs.models import LogFileAllowlist
from app.logs.protocol import (
    ON_SOURCE,
    REQUESTS,
    TO_VIEWER,
    WORKER,
    Alive,
    Ended,
    Lines,
    Opened,
    OpenRequest,
    Refused,
    encode,
    source_channel,
    viewer_channel,
)
from app.logs.sources import source_key
from app.logs.worker.hub import Hub, Timings
from auth_helpers import make_group, make_server
from collector_helpers import eventually, pinned_server
from conftest import owner_session
from logs_helpers import add_pattern, log_file
from test_log_running import source_of

FAST = Timings(count_every=0.1, close_after=0.5, alive_every=0.2, recheck_every=0.3)
PATTERN = "/var/log/nginx/*.log"


@pytest.fixture
async def valkey():
    client = valkey_client()
    yield client
    await client.aclose()


@asynccontextmanager
async def hub_running(sessions, valkey, heartbeat=None, **options) -> AsyncIterator[Hub]:
    """The hub running while inside, listening once inside; leaving stops it and its sources."""
    hub = Hub(sessions, valkey, timings=FAST, **options)
    task = asyncio.create_task(hub.run(heartbeat))
    try:
        await eventually(lambda: listened(valkey), timeout=5)
        yield hub
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await hub.stop()


async def listened(valkey) -> bool:
    return dict(await valkey.pubsub_numsub(REQUESTS)).get(REQUESTS.encode(), 0) > 0


class Viewer:
    """A socket's part of the protocol: its viewer channel and the source channels it watches, collected."""

    def __init__(self, valkey):
        self.socket_id = uuid4().hex
        self.answers: list = []
        self.on_source: dict[str, list] = {}
        self._valkey = valkey
        self._pubsub = valkey.pubsub()
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "Viewer":
        await self._subscribe(viewer_channel(self.socket_id))
        self._task = asyncio.create_task(self._collect())
        return self

    async def __aexit__(self, *exc) -> None:
        assert self._task is not None
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        await self._pubsub.aclose()

    async def _subscribe(self, channel: str) -> None:
        await self._pubsub.subscribe(channel)
        await eventually(lambda: self._count(channel), timeout=5)

    async def _count(self, channel: str) -> bool:
        return dict(await self._valkey.pubsub_numsub(channel)).get(channel.encode(), 0) > 0

    async def _collect(self) -> None:
        while True:
            message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None:
                continue
            channel = message["channel"].decode()
            if channel == viewer_channel(self.socket_id):
                self.answers.append(TO_VIEWER.validate_json(message["data"]))
            else:
                self.on_source[channel.removeprefix("logs:source:")].append(ON_SOURCE.validate_json(message["data"]))

    async def open(self, source) -> Opened | Refused:
        """Watches the source's channel, then asks for it, and returns the answer."""
        request_id = await self.ask(source)
        return await self.answer(request_id)

    async def ask(self, source) -> str:
        key = source_key(source)
        if key not in self.on_source:
            self.on_source[key] = []
            # A pubsub reads its confirmations in _collect, so wait on the count instead.
            await self._pubsub.subscribe(source_channel(key))
            await eventually(lambda: self._count(source_channel(key)), timeout=5)
        request_id = uuid4().hex
        request = OpenRequest(type="open", socket_id=self.socket_id, request_id=request_id, source=source)
        await self._valkey.publish(REQUESTS, encode(request))
        return request_id

    async def answer(self, request_id: str) -> Opened | Refused:
        await eventually(lambda: any(answer.request_id == request_id for answer in self.answers), timeout=10)
        return next(answer for answer in self.answers if answer.request_id == request_id)

    async def leave(self, key: str) -> None:
        await self._pubsub.unsubscribe(source_channel(key))

    def lines(self, key: str) -> list[dict]:
        return [line for message in self.on_source[key] if isinstance(message, Lines) for line in message.lines]


def tails(fake_server) -> int:
    """How many tail -F run on the fake server: one per file source's channel. followers() counts each channel's
    wrapper processes too."""
    result = fake_server.exec("pgrep", "-c", "-f", "^tail .*-F")
    assert result.returncode in (0, 1), result.stderr  # 1: no process matched
    return int(result.stdout.strip() or 0)


async def file_server(fake_server, name: str) -> Server:
    """A pinned server whose group allows the nginx logs."""
    server = await pinned_server(fake_server, name)
    await add_pattern(server.server_group_id, PATTERN)
    return server


async def test_an_open_request_is_answered_opened(clean_auth, logs_sessions, fake_server, valkey):
    server = await file_server(fake_server, "hub-open")
    path = log_file("open")
    fake_server.append(path, "first\n")
    source = source_of(server.id, kind="file", path=path)
    key = source_key(source)

    async with hub_running(logs_sessions, valkey) as hub, Viewer(valkey) as viewer:
        answer = await viewer.open(source)
        assert answer == Opened(type="opened", request_id=answer.request_id, key=key, run_id=hub.run_id, lines=[],
                                last_seq=0)
        await eventually(lambda: [line["text"] for line in viewer.lines(key)] == ["first"])
        fake_server.append(path, "second\n")
        await eventually(lambda: [line["text"] for line in viewer.lines(key)] == ["first", "second"])


async def test_a_second_viewer_gets_the_held_lines_and_no_second_channel(clean_auth, logs_sessions, fake_server,
                                                                          valkey):
    server = await file_server(fake_server, "hub-second")
    path = log_file("second")
    fake_server.append(path, "a\nb\n")
    source = source_of(server.id, kind="file", path=path)
    key = source_key(source)
    before = await asyncio.to_thread(fake_server.sign_ins)

    async with hub_running(logs_sessions, valkey) as hub, Viewer(valkey) as first, Viewer(valkey) as second:
        await first.open(source)
        await eventually(lambda: len(first.lines(key)) == 2)

        answer = await second.open(source)
        assert isinstance(answer, Opened)
        assert [line["text"] for line in answer.lines] == ["a", "b"]
        assert answer.last_seq == 2
        assert len(hub.running) == 1
        assert await asyncio.to_thread(tails, fake_server) == 1
        await eventually(lambda: asyncio.to_thread(lambda: fake_server.sign_ins() > before))
        assert await asyncio.to_thread(fake_server.sign_ins) == before + 1


async def test_two_requests_at_once_start_one_source(clean_auth, logs_sessions, fake_server, valkey):
    server = await file_server(fake_server, "hub-twice")
    path = log_file("twice")
    fake_server.append(path, "")
    source = source_of(server.id, kind="file", path=path)

    async with hub_running(logs_sessions, valkey) as hub, Viewer(valkey) as first, Viewer(valkey) as second:
        asked = [await first.ask(source), await second.ask(source)]
        answers = [await first.answer(asked[0]), await second.answer(asked[1])]
        assert [type(answer) for answer in answers] == [Opened, Opened]
        assert list(hub.running) == [source_key(source)]
        await eventually(lambda: asyncio.to_thread(lambda: tails(fake_server) == 1))
        await asyncio.sleep(0.3)
        assert await asyncio.to_thread(tails, fake_server) == 1


async def missing(fake_server):
    return source_of(uuid4(), kind="journal")


async def windows(fake_server):
    server = await pinned_server(fake_server, "hub-windows", os="windows")
    return source_of(server.id, kind="journal")


async def unpinned(fake_server):
    group = await make_group("hub-unpinned-group")
    server = await make_server(group.id, "hub-unpinned", address=fake_server.host, port=fake_server.port)
    return source_of(server.id, kind="journal")


async def flagged(fake_server):
    server = await pinned_server(fake_server, "hub-flagged")
    async with owner_session() as session:
        await session.execute(update(Server).where(Server.id == server.id).values(host_key_changed_at=func.now()))
        await session.commit()
    return source_of(server.id, kind="journal")


async def outside(fake_server):
    server = await file_server(fake_server, "hub-outside")
    return source_of(server.id, kind="file", path="/var/log/nginx/deep/access.log")


async def unknown_container(fake_server):
    server = await pinned_server(fake_server, "hub-container")
    return source_of(server.id, kind="container", container_id="web-1")


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        (missing, "not_found"),
        (windows, "not_an_ssh_server"),
        (unpinned, "host_key_not_pinned"),
        (flagged, "host_key_changed"),
        (outside, "not_allowed"),
        (unknown_container, "not_found"),
    ],
)
async def test_a_request_is_refused(clean_auth, logs_sessions, fake_server, valkey, make, reason):
    source = await make(fake_server)

    async with hub_running(logs_sessions, valkey) as hub, Viewer(valkey) as viewer:
        answer = await viewer.open(source)
        assert answer == Refused(type="refused", request_id=answer.request_id, key=source_key(source), reason=reason)
        assert hub.running == {}


async def test_the_ninth_source_of_a_server_is_refused(clean_auth, logs_sessions, fake_server, valkey):
    server = await file_server(fake_server, "hub-ninth")
    sources = []
    for n in range(9):
        path = log_file(f"ninth{n}")
        fake_server.append(path, "")
        sources.append(source_of(server.id, kind="file", path=path))

    async with hub_running(logs_sessions, valkey) as hub, Viewer(valkey) as viewer:
        answers = [await viewer.open(source) for source in sources]
        assert [type(answer) for answer in answers[:8]] == [Opened] * 8
        assert isinstance(answers[8], Refused) and answers[8].reason == "too_many_sources"
        assert len(hub.running) == 8


async def test_a_source_without_subscribers_closes_after_close_after(clean_auth, logs_sessions, fake_server, valkey):
    server = await file_server(fake_server, "hub-close")
    path = log_file("close")
    fake_server.append(path, "")
    source = source_of(server.id, kind="file", path=path)

    async with hub_running(logs_sessions, valkey) as hub, Viewer(valkey) as viewer:
        await viewer.open(source)
        await eventually(lambda: asyncio.to_thread(lambda: tails(fake_server) == 1))
        await asyncio.sleep(FAST.close_after + 0.3)
        assert len(hub.running) == 1  # watched, so it stays

        await viewer.leave(source_key(source))
        await eventually(lambda: hub.running == {}, timeout=2)
        await eventually(lambda: asyncio.to_thread(lambda: fake_server.followers() == 0), timeout=2)


async def test_alive_is_published_with_the_run_id(clean_auth, logs_sessions, valkey):
    pubsub = valkey.pubsub()
    await pubsub.subscribe(WORKER)
    try:
        async with hub_running(logs_sessions, valkey, run_id="a" * 32):
            alive = []
            async with asyncio.timeout(5):
                while len(alive) < 2:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if message is not None:
                        alive.append(Alive.model_validate_json(message["data"]))
            assert alive == [Alive(type="alive", run_id="a" * 32)] * 2
    finally:
        await pubsub.aclose()


def test_the_run_id_is_new_for_each_hub():
    first, second = Hub(None, None), Hub(None, None)
    assert first.run_id != second.run_id
    assert len(first.run_id) == 32


async def test_a_removed_pattern_ends_the_source_with_not_allowed(clean_auth, logs_sessions, fake_server, valkey):
    server = await file_server(fake_server, "hub-unallowed")
    path = log_file("unallowed")
    fake_server.append(path, "")
    source = source_of(server.id, kind="file", path=path)
    key = source_key(source)

    async with hub_running(logs_sessions, valkey) as hub, Viewer(valkey) as viewer:
        await viewer.open(source)
        async with owner_session() as session:
            allowed = LogFileAllowlist.server_group_id == server.server_group_id
            await session.execute(delete(LogFileAllowlist).where(allowed))
            await session.commit()
        await eventually(lambda: viewer.on_source[key][-1:] == [Ended(type="ended", reason="not_allowed")], timeout=5)
        assert hub.running == {}


async def test_a_removed_server_ends_with_not_found(clean_auth, logs_sessions, fake_server, valkey):
    server = await pinned_server(fake_server, "hub-removed")
    source = source_of(server.id, kind="journal")
    key = source_key(source)

    with fake_server.fixture("journalctl", ""):
        async with hub_running(logs_sessions, valkey) as hub, Viewer(valkey) as viewer:
            await viewer.open(source)
            async with owner_session() as session:
                await session.execute(delete(Server).where(Server.id == server.id))
                await session.commit()
            await eventually(lambda: viewer.on_source[key][-1:] == [Ended(type="ended", reason="not_found")],
                             timeout=5)
            assert hub.running == {}


async def test_the_heartbeat_is_touched(clean_auth, logs_sessions, valkey, tmp_path):
    heartbeat = tmp_path / "heartbeat"

    async with hub_running(logs_sessions, valkey, heartbeat):
        await eventually(heartbeat.exists, timeout=2)
        touched = heartbeat.stat().st_mtime_ns
        await eventually(lambda: heartbeat.stat().st_mtime_ns > touched, timeout=2)


async def test_a_bad_request_is_skipped(clean_auth, logs_sessions, fake_server, valkey, caplog):
    server = await pinned_server(fake_server, "hub-bad")
    source = source_of(server.id, kind="journal")

    with fake_server.fixture("journalctl", ""):
        async with hub_running(logs_sessions, valkey), Viewer(valkey) as viewer:
            await valkey.publish(REQUESTS, '{"type": "open"}')
            assert isinstance(await viewer.open(source), Opened)
    assert "open request" in caplog.text

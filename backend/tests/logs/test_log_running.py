"""A running source against the fake server and a real Valkey: the backlog it holds, the lines it publishes per kind,
one sign-in shared by a server's sources, nothing left on the server when it stops, and its end."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from uuid import UUID

import pytest

from app.core.valkey import valkey_client
from app.logs.protocol import ON_SOURCE, Ended, Lines, source_channel
from app.logs.sources import SOURCES, source_key
from app.logs.worker.links import Links
from app.logs.worker.source import Limits, RunningSource
from collector_helpers import eventually, pinned_server
from logs_helpers import log_file

LIMITS = Limits(batch_every=0.05)
TEN = 1795773600000000  # 2026-11-27T10:00:00Z in microseconds


@pytest.fixture
async def valkey():
    client = valkey_client()
    yield client
    await client.aclose()


@asynccontextmanager
async def watching(valkey, key: str) -> AsyncIterator[list]:
    """The messages published on the source's channel, collected while inside."""
    pubsub = valkey.pubsub()
    await pubsub.subscribe(source_channel(key))
    async with asyncio.timeout(5):
        while (await pubsub.get_message(timeout=1.0) or {}).get("type") != "subscribe":
            pass
    messages: list = []

    async def collect() -> None:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is not None:
                messages.append(ON_SOURCE.validate_json(message["data"]))

    task = asyncio.create_task(collect())
    try:
        yield messages
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await pubsub.aclose()


def source_of(server_id: UUID, **fields):
    return SOURCES.validate_python({"server_id": str(server_id), **fields})


@asynccontextmanager
async def running(source, server, valkey, links: Links | None = None) -> AsyncIterator[tuple[RunningSource, list]]:
    """The source running while inside, and the sources passed to on_end; leaving stops it."""
    ran = RunningSource(source_key(source), source, server, links=links or Links(), valkey=valkey, limits=LIMITS)
    ended: list = []
    ran.start(ended.append)
    try:
        yield ran, ended
    finally:
        await ran.stop()


def streamed(messages: list) -> list[dict]:
    return [line for message in messages if isinstance(message, Lines) for line in message.lines]


async def test_a_file_source_holds_the_last_200_lines_then_streams_new_ones(clean_auth, logs_sessions, fake_server,
                                                                             valkey):
    server = await pinned_server(fake_server, "run-file")
    path = log_file("run")
    fake_server.append(path, "".join(f"line {n}\n" for n in range(1, 251)))
    source = source_of(server.id, kind="file", path=path)

    async with watching(valkey, source_key(source)) as messages, running(source, server, valkey) as (ran, _):
        await eventually(lambda: ran.snapshot()[1] == 200)
        lines, last_seq = ran.snapshot()
        assert last_seq == 200
        assert len(lines) == 200
        assert (lines[0]["seq"], lines[0]["text"]) == (1, "line 51")
        assert (lines[-1]["seq"], lines[-1]["text"]) == (200, "line 250")

        fake_server.append(path, "line 251\nline 252\nline 253\n")
        await eventually(lambda: [line["seq"] for line in streamed(messages)][-3:] == [201, 202, 203])
        assert [line["text"] for line in streamed(messages)][-3:] == ["line 251", "line 252", "line 253"]
        assert ran.snapshot()[1] == 203


async def test_a_journal_source_parses_the_stub_entries(clean_auth, logs_sessions, fake_server, valkey):
    server = await pinned_server(fake_server, "run-journal")
    entries = [
        {"__REALTIME_TIMESTAMP": str(TEN), "PRIORITY": "3", "_SYSTEMD_UNIT": "nginx.service", "MESSAGE": "boom"},
        {"__REALTIME_TIMESTAMP": str(TEN + 500000), "PRIORITY": "6", "MESSAGE": "fine"},
    ]
    fed = {"__REALTIME_TIMESTAMP": str(TEN + 1000000), "PRIORITY": "4", "_SYSTEMD_UNIT": "cron.service",
           "MESSAGE": "later"}
    source = source_of(server.id, kind="journal")

    with fake_server.fixture("journalctl", "".join(json.dumps(entry) + "\n" for entry in entries)):
        async with watching(valkey, source_key(source)) as messages, running(source, server, valkey) as (ran, _):
            await eventually(lambda: ran.snapshot()[1] == 2)
            assert ran.snapshot()[0] == [
                {"seq": 1, "time": "2026-11-27T10:00:00Z", "text": "boom", "level": "err", "unit": "nginx.service"},
                {"seq": 2, "time": "2026-11-27T10:00:00.500000Z", "text": "fine", "level": "info"},
            ]

            fake_server.feed("journalctl", json.dumps(fed) + "\n")
            await eventually(lambda: any(line["seq"] == 3 for line in streamed(messages)))
            assert streamed(messages)[-1] == {
                "seq": 3, "time": "2026-11-27T10:00:01Z", "text": "later", "level": "warning", "unit": "cron.service"
            }


async def test_a_container_source_takes_dockers_time(clean_auth, logs_sessions, fake_server, valkey):
    server = await pinned_server(fake_server, "run-container")
    source = source_of(server.id, kind="container", container_id="web-1")

    with fake_server.fixture("docker_logs", "2026-11-27T10:00:00.5Z hi\n"):
        async with running(source, server, valkey) as (ran, _):
            await eventually(lambda: ran.snapshot()[1] == 1)
            assert ran.snapshot() == ([{"seq": 1, "time": "2026-11-27T10:00:00.500000Z", "text": "hi"}], 1)


async def test_two_sources_of_a_server_share_one_sign_in(clean_auth, logs_sessions, fake_server, valkey):
    server = await pinned_server(fake_server, "run-shared")
    path = log_file("shared")
    fake_server.append(path, "a\n")
    links = Links()
    before = await asyncio.to_thread(fake_server.sign_ins)

    with fake_server.fixture("journalctl", '{"MESSAGE": "j"}\n'):
        async with (
            running(source_of(server.id, kind="file", path=path), server, valkey, links) as (file, _),
            running(source_of(server.id, kind="journal"), server, valkey, links) as (journal, _),
        ):
            await eventually(lambda: file.snapshot()[1] == 1 and journal.snapshot()[1] == 1)
            assert links.open_count() == 1
            await eventually(lambda: asyncio.to_thread(lambda: fake_server.sign_ins() > before))
            assert await asyncio.to_thread(fake_server.sign_ins) == before + 1
    assert links.open_count() == 0


async def test_stopping_a_quiet_source_leaves_no_process(clean_auth, logs_sessions, fake_server, valkey):
    server = await pinned_server(fake_server, "run-quiet")
    path = log_file("quiet")
    fake_server.append(path, "")

    async with running(source_of(server.id, kind="file", path=path), server, valkey):
        await eventually(lambda: asyncio.to_thread(lambda: fake_server.followers() > 0))
    await eventually(lambda: asyncio.to_thread(lambda: fake_server.followers() == 0), timeout=5)


async def test_a_container_that_stops_ends_with_exited(clean_auth, logs_sessions, fake_server, valkey):
    server = await pinned_server(fake_server, "run-exited")
    source = source_of(server.id, kind="container", container_id="web-1")

    with fake_server.fixture("docker_logs", "2026-11-27T10:00:00Z bye\n", exit=3):
        async with watching(valkey, source_key(source)) as messages, running(source, server, valkey) as (ran, ended):
            await eventually(lambda: ended == [ran])
            await eventually(lambda: messages and isinstance(messages[-1], Ended))
            assert messages[-1] == Ended(type="ended", reason="exited", status=3)
            assert [line["text"] for line in streamed(messages)] == ["bye"]

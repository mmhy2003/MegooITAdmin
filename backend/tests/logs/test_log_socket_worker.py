"""WS /api/ws/logs and the logs worker: a source ends with worker_unavailable when no worker answers or the worker
stops saying it is alive, and with worker_restarted when another worker run speaks. With the real hub, two admins
watching one file share one channel and one sign-in, and the worker's cap reaches the browser as skipped counts."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import pytest
from auth_helpers import add_grant, events, make_group, make_server, signed_in
from collector_helpers import eventually, pinned_server
from logs_helpers import FakeWorker, add_pattern, log_file, receive, receive_type, subscribe
from socket_helpers import connect, serving
from test_log_hub import tails

from app.auth.sessions import COOKIE
from app.core.valkey import valkey_client
from app.logs.protocol import REQUESTS
from app.logs.sources import SOURCES, describe, source_key
from app.logs.worker.hub import Hub, Timings
from app.logs.worker.source import Limits
from app.main import create_app

PATH = "/api/ws/logs"
OWNER = "owner@example.com"
PATTERN = "/var/log/nginx/*.log"
FAST = Timings(count_every=0.1, close_after=0.5, alive_every=0.2, recheck_every=0.3)


@pytest.fixture
async def socket_base(api):
    async with serving(create_app()) as base:
        yield base


@pytest.fixture
async def client():
    client = valkey_client()
    yield client
    await client.aclose()


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr("app.logs.socket.WATCH_EVERY", 0.05)
    monkeypatch.setattr("app.logs.socket.OPEN_TIMEOUT", 0.3)


@asynccontextmanager
async def hub_running(sessions, client, **options) -> AsyncIterator[Hub]:
    """The real hub running while inside, listening once inside; leaving stops it and its sources."""
    hub = Hub(sessions, client, timings=FAST, **options)
    task = asyncio.create_task(hub.run())
    try:
        await eventually(lambda: listened(client), timeout=5, every=0.02)
        yield hub
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await hub.stop()


async def listened(client) -> bool:
    return dict(await client.pubsub_numsub(REQUESTS)).get(REQUESTS.encode(), 0) > 0


async def staging_server(name: str = "web-1"):
    group = await make_group("staging")
    await add_pattern(group.id, PATTERN)
    return group, await make_server(group.id, name)


def file_source(server_id, path: str) -> dict:
    return {"kind": "file", "server_id": str(server_id), "path": path}


def key_of(source: dict) -> str:
    return source_key(SOURCES.validate_python(source))


def described(source: dict) -> dict:
    return describe(SOURCES.validate_python(source))


async def closed_with(reason: str) -> bool:
    """Whether every stream_closed so far, one at least, has this reason."""
    reasons = [event.result_detail["reason"] for event in await events("logs.stream_closed")]
    return bool(reasons) and set(reasons) == {reason}


async def lines_of(ws, key: str, count: int, timeout: float = 10) -> list[dict]:
    """The lines of this source, backlog or not, until there are this many."""
    lines: list[dict] = []
    async with asyncio.timeout(timeout):
        while len(lines) < count:
            message = await receive(ws, timeout)
            if message["type"] == "lines" and message["source"] == key:
                lines += message["lines"]
    return lines


async def test_no_worker_ends_the_source_with_worker_unavailable(api, clock, socket_base):
    _, server = await staging_server()
    source = file_source(server.id, log_file("none"))
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            reply = await subscribe(ws, [source])
            assert reply == {"type": "subscribed", "sources": [{"id": key_of(source), "source": described(source)}],
                             "denied": []}
            assert await receive(ws) == {"type": "ended", "source": key_of(source), "reason": "worker_unavailable"}
            await eventually(lambda: closed_with("worker_unavailable"), timeout=5, every=0.02)


async def test_a_worker_that_does_not_answer_ends_with_worker_unavailable(api, clock, socket_base, client):
    _, server = await staging_server()
    source = file_source(server.id, log_file("mute"))
    async with FakeWorker(client, answer=False) as worker, signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            reply = await subscribe(ws, [source])
            assert [one["id"] for one in reply["sources"]] == [key_of(source)]
            assert await receive(ws) == {"type": "ended", "source": key_of(source), "reason": "worker_unavailable"}
            assert len(worker.requests) == 1
            await eventually(lambda: closed_with("worker_unavailable"), timeout=5, every=0.02)


async def test_another_run_id_ends_every_source_with_worker_restarted(api, clock, socket_base, client):
    _, server = await staging_server()
    a, b = file_source(server.id, log_file("a")), file_source(server.id, log_file("b"))
    async with FakeWorker(client) as worker, signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await subscribe(ws, [a, b])
            await receive_type(ws, "lines")
            await receive_type(ws, "lines")

            await worker.alive()  # the run that answered: nothing ends
            await worker.alive("e" * 32)
            ended = [await receive(ws), await receive(ws)]
            assert sorted(ended, key=lambda message: message["source"]) == [
                {"type": "ended", "source": key, "reason": "worker_restarted"} for key in sorted([key_of(a), key_of(b)])
            ]
            await eventually(lambda: closed_with("worker_restarted"), timeout=5, every=0.02)


async def test_no_alive_ends_every_source_with_worker_unavailable(api, clock, socket_base, client, monkeypatch):
    monkeypatch.setattr("app.logs.socket.ALIVE_TIMEOUT", 0.5)
    _, server = await staging_server()
    a, b = file_source(server.id, log_file("a")), file_source(server.id, log_file("b"))
    async with FakeWorker(client), signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await subscribe(ws, [a, b])
            await receive_type(ws, "lines")
            await receive_type(ws, "lines")
            ended = [await receive(ws), await receive(ws)]
            assert sorted(ended, key=lambda message: message["source"]) == [
                {"type": "ended", "source": key, "reason": "worker_unavailable"}
                for key in sorted([key_of(a), key_of(b)])
            ]
            await eventually(lambda: closed_with("worker_unavailable"), timeout=5, every=0.02)

            # The socket stays open: with the worker alive again, a new subscribe opens.
            await subscribe(ws, [a])
            assert (await receive_type(ws, "lines"))["source"] == key_of(a)


async def test_two_admins_watch_one_file_over_one_channel(api, clock, socket_base, client, logs_sessions,
                                                          fake_server):
    server = await pinned_server(fake_server, "two-admins")
    await add_pattern(server.server_group_id, PATTERN)
    path = log_file("two")
    fake_server.append(path, "".join(f"line {n}\n" for n in range(1, 6)))
    source = file_source(server.id, path)
    key = key_of(source)
    before = await asyncio.to_thread(fake_server.sign_ins)

    async with (
        hub_running(logs_sessions, client) as hub,
        signed_in(api, clock, "ada@example.com") as (ada, ada_browser),
        signed_in(api, clock, "bob@example.com") as (bob, bob_browser),
    ):
        await add_grant(ada.id, server.server_group_id, "admin")
        await add_grant(bob.id, server.server_group_id, "admin")
        async with (
            connect(socket_base, PATH, ada_browser.cookies.get(COOKIE)) as first,
            connect(socket_base, PATH, bob_browser.cookies.get(COOKIE)) as second,
        ):
            assert [one["id"] for one in (await subscribe(first, [source]))["sources"]] == [key]
            assert [line["text"] for line in await lines_of(first, key, 5)] == [f"line {n}" for n in range(1, 6)]

            assert [one["id"] for one in (await subscribe(second, [source]))["sources"]] == [key]
            backlog = await receive(second)
            assert backlog["backlog"] is True
            assert [line["text"] for line in backlog["lines"]] == [f"line {n}" for n in range(1, 6)]

            fake_server.append(path, "six\nseven\neight\n")
            seen = [await lines_of(first, key, 3), await lines_of(second, key, 3)]
            assert [(line["seq"], line["text"]) for line in seen[0]] == [(6, "six"), (7, "seven"), (8, "eight")]
            assert [(line["seq"], line["text"]) for line in seen[1]] == [(6, "six"), (7, "seven"), (8, "eight")]

            assert len(hub.running) == 1
            # followers() counts each channel's wrapper processes too, so one channel is one tail -F.
            assert await asyncio.to_thread(tails, fake_server) == 1
            assert await asyncio.to_thread(fake_server.sign_ins) == before + 1

        await eventually(lambda: not hub.running, timeout=2, every=0.05)
        await eventually(lambda: asyncio.to_thread(lambda: fake_server.followers() == 0), timeout=5)


async def test_the_cap_reaches_the_browser_as_skipped(api, clock, socket_base, client, logs_sessions, fake_server):
    server = await pinned_server(fake_server, "capped")
    await add_pattern(server.server_group_id, PATTERN)
    path = log_file("capped")
    fake_server.append(path, "")
    source = file_source(server.id, path)
    key = key_of(source)

    async with (
        hub_running(logs_sessions, client, limits=Limits(max_lines_per_second=20)),
        signed_in(api, clock, OWNER, "owner") as (_, browser),
    ):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await subscribe(ws, [source])
            assert (await receive(ws))["lines"] == []
            fake_server.append(path, "".join(f"burst {n}\n" for n in range(200)))

            kept = skipped = 0
            async with asyncio.timeout(10):
                while kept + skipped < 200:
                    message = await receive(ws)
                    if message["type"] == "lines":
                        kept += len(message["lines"])
                    elif message["type"] == "skipped":
                        skipped += message["count"]
            assert kept + skipped == 200
            assert 0 < kept < 200
            assert skipped > 0

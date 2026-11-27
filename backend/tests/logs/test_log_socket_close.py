"""WS /api/ws/logs: how a source ends for a socket. A new subscribe replaces the set, the worker's end is told, an idle
viewer's sources end while the socket stays open, the recheck ends a source after a lost right, and a socket that
closes records its remaining sources closed. A slow browser closes with 1013 and an unreachable Valkey with 1011."""

import asyncio
import json

import pytest
from auth_helpers import add_grant, events, make_group, make_server, set_switch, signed_in
from collector_helpers import eventually
from conftest import owner_session
from logs_helpers import FakeWorker, add_pattern, log_file, receive, receive_type, subscribe, text_line, viewers
from socket_helpers import close_code, connect, serving
from sqlalchemy import text

import app.logs.socket as logs_socket
from app.auth.sessions import COOKIE
from app.core.valkey import valkey_client
from app.logs.protocol import Ended, Lines
from app.logs.sources import SOURCES, describe, source_key
from app.main import create_app

PATH = "/api/ws/logs"
OWNER = "owner@example.com"
OPERATOR = "otto@example.com"
PATTERN = "/var/log/nginx/*.log"


@pytest.fixture
async def socket_base(api):
    async with serving(create_app()) as base:
        yield base


@pytest.fixture
async def client():
    client = valkey_client()
    yield client
    await client.aclose()


@pytest.fixture
async def worker(client):
    async with FakeWorker(client) as worker:
        yield worker


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    """Quick rechecks and watches. Only the idle tests make a viewer idle quickly, so that no other test races it."""
    monkeypatch.setattr("app.logs.socket.RECHECK_EVERY", 0.2)
    monkeypatch.setattr("app.logs.socket.WATCH_EVERY", 0.05)
    monkeypatch.setattr("app.logs.socket.idle_after", lambda: 60.0)


@pytest.fixture
def quick_idle(monkeypatch):
    monkeypatch.setattr("app.logs.socket.idle_after", lambda: 0.5)


async def owner_sql(sql: str, **params) -> None:
    async with owner_session() as session:
        await session.execute(text(sql), params)
        await session.commit()


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


async def no_viewers(client, key: str) -> bool:
    return await viewers(client, key) == 0


async def closed_events() -> list:
    return await events("logs.stream_closed")


async def nothing_for(ws, seconds: float) -> None:
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(ws.recv(), seconds)


async def test_a_subscribe_replaces_the_set(api, clock, socket_base, client, worker):
    _, server = await staging_server()
    a, b = file_source(server.id, log_file("a")), file_source(server.id, log_file("b"))
    worker.backlogs[key_of(a)] = ([text_line(1, "a")], 1)
    worker.backlogs[key_of(b)] = ([text_line(1, "b")], 1)
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await subscribe(ws, [a])
            assert (await receive(ws))["source"] == key_of(a)

            reply = await subscribe(ws, [a, b])
            assert [one["id"] for one in reply["sources"]] == sorted([key_of(a), key_of(b)])
            assert await receive(ws) == {"type": "lines", "source": key_of(b), "lines": [text_line(1, "b")],
                                         "backlog": True}
            assert [source_key(request.source) for request in worker.requests] == [key_of(a), key_of(b)]

            reply = await subscribe(ws, [b])
            assert reply == {"type": "subscribed", "sources": [{"id": key_of(b), "source": described(b)}],
                             "denied": []}
            await eventually(lambda: no_viewers(client, key_of(a)), timeout=5, every=0.02)
            assert await viewers(client, key_of(b)) == 1
            await nothing_for(ws, 0.2)
            await eventually(closed_events, timeout=5, every=0.02)
            [closed] = await closed_events()
            assert closed.result_detail["sources"] == [described(a)]
            assert closed.result_detail["reason"] == "left"


async def test_an_ended_source_is_told_and_closed(api, clock, socket_base, client, worker):
    _, server = await staging_server()
    source = file_source(server.id, log_file("ended"))
    key = key_of(source)
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await subscribe(ws, [source])
            assert (await receive(ws))["backlog"] is True
            await worker.publish(key, Ended(type="ended", reason="exited", status=3))
            assert await receive(ws) == {"type": "ended", "source": key, "reason": "exited", "status": 3}
            await eventually(lambda: no_viewers(client, key), timeout=5, every=0.02)
            await worker.publish(key, Lines(type="lines", lines=[text_line(1, "late")]))
            await nothing_for(ws, 0.2)
    await eventually(closed_events, timeout=5, every=0.02)
    [closed] = await closed_events()
    assert (closed.result_detail["sources"], closed.result_detail["reason"]) == ([described(source)], "exited")


async def test_closing_the_socket_records_closed_with_duration_and_left(api, clock, socket_base, worker):
    group, server = await staging_server()
    first, second = file_source(server.id, log_file("one")), file_source(server.id, log_file("two"))
    async with signed_in(api, clock, OWNER, "owner") as (owner, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await subscribe(ws, [first, second])
            await asyncio.sleep(1.2)
        await eventually(closed_events, timeout=5, every=0.02)
    [closed] = await closed_events()
    assert (closed.actor_id, closed.target_id, closed.target_name) == (str(owner.id), str(server.id), "web-1")
    assert closed.context == {"server_group_id": str(group.id)}
    detail = closed.result_detail
    assert detail["sources"] == [described(s) for s in sorted([first, second], key=key_of)]
    assert detail["reason"] == "left"
    # Whole seconds: an audit event holds no floats.
    assert detail["duration_seconds"] in (1, 2)


async def test_idle_ends_every_source_and_the_socket_stays_open(api, clock, socket_base, client, worker, quick_idle):
    _, server = await staging_server()
    first, second = file_source(server.id, log_file("one")), file_source(server.id, log_file("two"))
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await subscribe(ws, [first, second])
            ended = [await receive_type(ws, "ended", timeout=3) for _ in range(2)]
            assert sorted(e["source"] for e in ended) == sorted([key_of(first), key_of(second)])
            assert {e["reason"] for e in ended} == {"idle"}
            await eventually(lambda: no_viewers(client, key_of(first)), timeout=5, every=0.02)
            await eventually(closed_events, timeout=5, every=0.02)
            [closed] = await closed_events()
            assert closed.result_detail["reason"] == "idle"
            assert len(closed.result_detail["sources"]) == 2

            reply = await subscribe(ws, [first])
            assert [one["id"] for one in reply["sources"]] == [key_of(first)]
            assert (await receive(ws))["backlog"] is True


async def test_active_resets_the_idle_timer(api, clock, socket_base, worker, quick_idle):
    _, server = await staging_server()
    source = file_source(server.id, log_file("active"))
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await subscribe(ws, [source])
            assert (await receive(ws))["backlog"] is True
            for _ in range(5):
                await ws.send(json.dumps({"type": "active"}))
                await nothing_for(ws, 0.2)
            assert (await receive(ws, timeout=3))["reason"] == "idle"


async def _ended_by_recheck(api, clock, socket_base, client, change, reason: str) -> None:
    """An operator of staging follows a file; after change(grant, group, server) the recheck ends it with reason."""
    group, server = await staging_server()
    source = file_source(server.id, log_file("recheck"))
    key = key_of(source)
    async with signed_in(api, clock, OPERATOR) as (otto, browser):
        grant = await add_grant(otto.id, group.id, "operator", view_logs=True)
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            assert (await subscribe(ws, [source]))["denied"] == []
            assert (await receive(ws))["backlog"] is True
            await change(grant, group, server)
            assert await receive(ws, timeout=3) == {"type": "ended", "source": key, "reason": reason}
            await eventually(lambda: no_viewers(client, key), timeout=5, every=0.02)
    await eventually(closed_events, timeout=5, every=0.02)
    [closed] = await closed_events()
    assert closed.result_detail["reason"] == reason


async def test_the_recheck_ends_a_source_after_a_lost_right(api, clock, socket_base, client, worker):
    async def change(grant, group, server):
        await set_switch(grant.id, "view_logs", False)

    await _ended_by_recheck(api, clock, socket_base, client, change, "forbidden")


async def test_the_recheck_ends_a_source_after_a_removed_pattern(api, clock, socket_base, client, worker):
    async def change(grant, group, server):
        await owner_sql("DELETE FROM log_file_allowlist WHERE server_group_id = :group_id", group_id=group.id)

    await _ended_by_recheck(api, clock, socket_base, client, change, "not_allowed")


async def test_the_recheck_ends_a_source_of_a_moved_server(api, clock, socket_base, client, worker):
    async def change(grant, group, server):
        production = await make_group("production")
        await owner_sql("UPDATE servers SET server_group_id = :group_id WHERE id = :id", group_id=production.id,
                        id=server.id)

    await _ended_by_recheck(api, clock, socket_base, client, change, "not_found")


async def test_an_ended_session_closes_4401_with_signed_out(api, clock, socket_base, worker):
    _, server = await staging_server()
    source = file_source(server.id, log_file("session"))
    async with signed_in(api, clock, OWNER, "owner") as (owner, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await subscribe(ws, [source])
            await ws.send(json.dumps({"type": "active"}))
            await owner_sql("DELETE FROM auth_sessions WHERE user_id = :user_id", user_id=owner.id)
            assert await close_code(ws) == 4401
        await eventually(closed_events, timeout=5, every=0.02)
    [closed] = await closed_events()
    assert (closed.result_detail["sources"], closed.result_detail["reason"]) == ([described(source)], "signed_out")


async def test_a_browser_that_reads_too_slowly_is_closed_1013(api, clock, socket_base, worker, monkeypatch):
    monkeypatch.setattr("app.logs.socket.QUEUE_LIMIT", 2)
    sent = 0
    real_send = logs_socket._send

    async def stuck(websocket, message):
        nonlocal sent
        sent += 1
        if sent > 1:
            await asyncio.Event().wait()
        await real_send(websocket, message)

    monkeypatch.setattr("app.logs.socket._send", stuck)
    _, server = await staging_server()
    source = file_source(server.id, log_file("slow"))
    key = key_of(source)
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await subscribe(ws, [source])
            for seq in range(1, 6):
                await worker.publish(key, Lines(type="lines", lines=[text_line(seq, "x")]))
            assert await close_code(ws) == 1013
        await eventually(closed_events, timeout=5, every=0.02)
    [closed] = await closed_events()
    assert closed.result_detail["reason"] == "left"


async def test_valkey_unreachable_closes_1011(api, clock, socket_base, monkeypatch):
    from valkey.asyncio import from_url

    monkeypatch.setattr("app.logs.socket.valkey_client", lambda: from_url("valkey://127.0.0.1:1/0"))
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            assert await close_code(ws) == 1011


async def test_a_subscribe_that_fails_midway_records_every_opened_source_closed(
    api, clock, socket_base, worker, monkeypatch
):
    real_subscribe = logs_socket._Channels.subscribe
    calls = 0

    async def second_fails(self, channel):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise logs_socket._Closed(1011)
        await real_subscribe(self, channel)

    monkeypatch.setattr(logs_socket._Channels, "subscribe", second_fails)
    _, server = await staging_server()
    sources = [file_source(server.id, log_file(name)) for name in ("one", "two", "three")]
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await ws.send(json.dumps({"type": "subscribe", "sources": sources}))
            assert await close_code(ws) == 1011
        await eventually(closed_events, timeout=5, every=0.02)
    [opened] = await events("logs.stream_opened")
    [closed] = await closed_events()
    assert closed.result_detail["sources"] == opened.result_detail["sources"] == [
        described(s) for s in sorted(sources, key=key_of)
    ]

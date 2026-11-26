"""WS /api/ws/metrics: a person subscribes to the servers on their screen, gets the live samples of those they see
in the view they asked for, and is told which ones they do not see."""

import asyncio
import json
import uuid
from datetime import UTC, datetime

import pytest
from auth_helpers import EMAIL, PASSWORD, add_grant, events, make_group, make_server, make_user, signed_in
from conftest import owner_session
from socket_helpers import close_code, connect, serving
from sqlalchemy import text
from websockets.exceptions import InvalidStatus

from app.auth.sessions import COOKIE
from app.core.valkey import valkey_client
from app.main import create_app
from app.metrics import socket as metrics_socket
from app.metrics.fanout import channel, publish
from app.metrics.overview import overview_message, summarize
from app.metrics.samples import Reading, Sample

PATH = "/api/ws/metrics"
OWNER = "owner@example.com"
OPERATOR = "otto@example.com"
NOW = datetime(2026, 11, 25, 10, 0, 5, tzinfo=UTC)


@pytest.fixture
async def socket_base(api):
    async with serving(create_app()) as base:
        yield base


@pytest.fixture
async def client():
    client = valkey_client()
    yield client
    await client.aclose()


async def on_valkey(client, server_id: uuid.UUID, count: int = 1) -> None:
    """Waits until Valkey counts this many subscribers of the server: a subscribe is answered before Valkey applied
    it."""
    async with asyncio.timeout(5):
        while (await client.pubsub_numsub(channel(server_id)))[0][1] != count:
            await asyncio.sleep(0.02)


async def receive(ws) -> dict:
    return json.loads(await asyncio.wait_for(ws.recv(), 5))


async def subscribe(ws, view: str, ids) -> dict:
    await ws.send(json.dumps({"type": "subscribe", "view": view, "server_ids": [str(id_) for id_ in ids]}))
    reply = await receive(ws)
    assert reply["type"] == "subscribed", reply
    return reply


def _sample(server_id: uuid.UUID, *readings: tuple[str, str, float]) -> Sample:
    return Sample(
        time=NOW,
        server_id=server_id,
        readings=tuple(Reading(metric=metric, instance=instance, value=value) for metric, instance, value in readings),
    )


FULL_READINGS = (
    ("cpu.used_percent", "", 12.5),
    ("mem.used_percent", "", 40.0),
    ("load.1m", "", 0.5),
    ("disk.used_percent", "/", 71.0),
    ("net.rx_bytes_per_sec", "eth0", 100.0),
    ("net.tx_bytes_per_sec", "eth0", 50.0),
)


async def test_no_cookie_closes_4401(socket_base):
    async with connect(socket_base, PATH) as ws:
        assert await close_code(ws) == 4401


async def test_a_pending_session_closes_4401(api, socket_base):
    await make_user()
    response = await api.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200, response.text
    async with connect(socket_base, PATH, api.cookies[COOKIE]) as ws:
        assert await close_code(ws) == 4401


async def test_a_foreign_origin_gets_403(api, clock, socket_base):
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        cookie = browser.cookies.get(COOKIE)
        with pytest.raises(InvalidStatus) as refused:
            async with connect(socket_base, PATH, cookie, origin="http://evil.example"):
                pass
    assert refused.value.response.status_code == 403


async def test_overview_view_sends_six_numbers(api, clock, socket_base, client):
    s1 = (await make_server((await make_group("staging")).id, "web-1")).id
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            reply = await subscribe(ws, "overview", [s1])
            assert reply == {"type": "subscribed", "server_ids": [str(s1)], "denied": []}
            await on_valkey(client, s1)
            sample = _sample(s1, *FULL_READINGS)
            await publish(client, sample)
            assert await receive(ws) == json.loads(json.dumps(overview_message(summarize(sample))))


async def test_full_view_sends_every_reading(api, clock, socket_base, client):
    s1 = (await make_server((await make_group("staging")).id, "web-1")).id
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await subscribe(ws, "full", [s1])
            await on_valkey(client, s1)
            await publish(client, _sample(s1, *FULL_READINGS))
            assert await receive(ws) == {
                "type": "sample",
                "server_id": str(s1),
                "time": "2026-11-25T10:00:05Z",
                "readings": [list(reading) for reading in FULL_READINGS],
            }


async def test_a_server_of_another_group_is_denied_recorded_once_and_never_sent(api, clock, socket_base, client):
    staging, production = await make_group("staging"), await make_group("production")
    s1 = (await make_server(staging.id, "web-1")).id
    p1 = (await make_server(production.id, "db-1")).id
    missing = uuid.uuid4()
    async with signed_in(api, clock, OPERATOR) as (otto, browser):
        await add_grant(otto.id, staging.id, "operator")
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            reply = await subscribe(ws, "overview", [s1, p1, missing])
            assert reply["server_ids"] == [str(s1)]
            assert reply["denied"] == sorted([str(p1), str(missing)])
            [event] = await events("access.denied")
            assert event.result_detail == {"required": "group", "route": "WS /api/ws/metrics", "server_ids": [str(p1)]}

            await on_valkey(client, s1)
            assert (await client.pubsub_numsub(channel(p1)))[0][1] == 0
            await publish(client, _sample(p1, ("cpu.used_percent", "", 1.0)))
            await publish(client, _sample(s1, ("cpu.used_percent", "", 2.0)))
            message = await receive(ws)
            assert (message["server_id"], message["cpu"]) == (str(s1), 2.0)

            reply = await subscribe(ws, "overview", [p1])
            assert reply == {"type": "subscribed", "server_ids": [], "denied": [str(p1)]}
            assert len(await events("access.denied")) == 1


async def test_a_new_subscribe_replaces_the_old_one(api, clock, socket_base, client):
    group = await make_group("staging")
    s1, s2 = (await make_server(group.id, "web-1")).id, (await make_server(group.id, "web-2")).id
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await subscribe(ws, "overview", [s1])
            await on_valkey(client, s1)
            await subscribe(ws, "overview", [s2])
            await on_valkey(client, s2)
            await on_valkey(client, s1, 0)
            await publish(client, _sample(s1, ("cpu.used_percent", "", 1.0)))
            await publish(client, _sample(s2, ("cpu.used_percent", "", 2.0)))
            message = await receive(ws)
            assert (message["type"], message["server_id"]) == ("overview", str(s2))

            await subscribe(ws, "full", [s2])
            await publish(client, _sample(s2, ("cpu.used_percent", "", 3.0)))
            message = await receive(ws)
            assert (message["type"], message["readings"]) == ("sample", [["cpu.used_percent", "", 3.0]])


async def test_an_invalid_message_gets_an_error_and_the_socket_stays_open(api, clock, socket_base):
    s1 = (await make_server((await make_group("staging")).id, "web-1")).id
    too_many = {"type": "subscribe", "view": "overview", "server_ids": [str(uuid.uuid4()) for _ in range(201)]}
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            for text in [
                "nope",
                json.dumps({"type": "subscribe", "view": "x", "server_ids": []}),
                json.dumps(too_many),
                "x" * 16_385,
            ]:
                await ws.send(text)
                assert await receive(ws) == {"type": "error", "detail": "invalid_message"}
            assert (await subscribe(ws, "overview", [s1]))["server_ids"] == [str(s1)]


async def test_an_empty_subscribe_is_allowed(api, clock, socket_base):
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            assert await subscribe(ws, "overview", []) == {"type": "subscribed", "server_ids": [], "denied": []}


@pytest.fixture
def quick_recheck(monkeypatch):
    monkeypatch.setattr("app.metrics.socket.RECHECK_EVERY", 0.2)


async def owner_sql(sql: str, **params) -> None:
    async with owner_session() as session:
        await session.execute(text(sql), params)
        await session.commit()


async def last_seen(user_id: uuid.UUID) -> list[datetime]:
    async with owner_session() as session:
        rows = await session.execute(
            text("SELECT last_seen_at FROM auth_sessions WHERE user_id = :user_id"), {"user_id": user_id}
        )
        return [row[0] for row in rows]


async def test_an_ended_session_is_noticed_by_the_recheck(api, clock, socket_base, quick_recheck):
    s1 = (await make_server((await make_group("staging")).id, "web-1")).id
    async with signed_in(api, clock, OWNER, "owner") as (owner, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await subscribe(ws, "overview", [s1])
            await owner_sql("DELETE FROM auth_sessions WHERE user_id = :user_id", user_id=owner.id)
            assert await close_code(ws) == 4401


async def test_an_idle_session_is_noticed(api, clock, socket_base, quick_recheck):
    s1 = (await make_server((await make_group("staging")).id, "web-1")).id
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await subscribe(ws, "overview", [s1])
            clock.advance(minutes=61)
            assert await close_code(ws) == 4401


async def _dropped_after(api, clock, socket_base, client, change) -> None:
    """An operator of staging subscribes to s1; after change(otto, s1, production) the recheck drops s1 and its
    samples no longer arrive."""
    staging, production = await make_group("staging"), await make_group("production")
    s1 = (await make_server(staging.id, "web-1")).id
    async with signed_in(api, clock, OPERATOR) as (otto, browser):
        await add_grant(otto.id, staging.id, "operator")
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await subscribe(ws, "overview", [s1])
            await on_valkey(client, s1)
            await change(otto, s1, production)
            assert await receive(ws) == {"type": "subscribed", "server_ids": [], "denied": [str(s1)]}
            await on_valkey(client, s1, 0)
            await publish(client, _sample(s1, ("cpu.used_percent", "", 1.0)))
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(ws.recv(), 0.5)


async def test_a_removed_grant_drops_the_server(api, clock, socket_base, client, quick_recheck):
    async def change(otto, s1, production):
        await owner_sql("DELETE FROM role_grants WHERE user_id = :user_id", user_id=otto.id)

    await _dropped_after(api, clock, socket_base, client, change)


async def test_a_moved_server_is_dropped(api, clock, socket_base, client, quick_recheck):
    async def change(otto, s1, production):
        await owner_sql("UPDATE servers SET server_group_id = :group_id WHERE id = :id", group_id=production.id, id=s1)

    await _dropped_after(api, clock, socket_base, client, change)


async def test_a_removed_server_is_dropped(api, clock, socket_base, client, quick_recheck):
    async def change(otto, s1, production):
        await owner_sql("DELETE FROM servers WHERE id = :id", id=s1)

    await _dropped_after(api, clock, socket_base, client, change)


async def test_the_recheck_never_touches_the_session(api, clock, socket_base, monkeypatch, quick_recheck):
    rechecks = 0
    real_recheck = metrics_socket.recheck

    async def counted(signed):
        nonlocal rechecks
        rechecks += 1
        return await real_recheck(signed)

    monkeypatch.setattr("app.metrics.socket.recheck", counted)
    async with signed_in(api, clock, OWNER, "owner") as (owner, browser):
        before = await last_seen(owner.id)
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await subscribe(ws, "overview", [])
            clock.advance(minutes=5)
            async with asyncio.timeout(5):
                while rechecks < 3:
                    await asyncio.sleep(0.05)
        assert await last_seen(owner.id) == before


async def test_a_browser_that_reads_too_slowly_is_closed_1013(api, clock, socket_base, client, monkeypatch):
    monkeypatch.setattr("app.metrics.socket.QUEUE_LIMIT", 2)
    sent = 0
    real_send = metrics_socket._send

    async def stuck(websocket, message):
        nonlocal sent
        sent += 1
        if sent > 1:
            await asyncio.Event().wait()
        await real_send(websocket, message)

    monkeypatch.setattr("app.metrics.socket._send", stuck)
    s1 = (await make_server((await make_group("staging")).id, "web-1")).id
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await subscribe(ws, "overview", [s1])
            await on_valkey(client, s1)
            for n in range(5):
                await publish(client, _sample(s1, ("cpu.used_percent", "", float(n))))
            assert await close_code(ws) == 1013


async def test_valkey_unreachable_closes_1011(api, clock, socket_base, monkeypatch):
    from valkey.asyncio import from_url

    monkeypatch.setattr("app.metrics.socket.valkey_client", lambda: from_url("valkey://127.0.0.1:1/0"))
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            assert await close_code(ws) == 1011


async def test_a_lost_valkey_connection_closes_1011(api, clock, socket_base, client):
    s1 = (await make_server((await make_group("staging")).id, "web-1")).id
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await subscribe(ws, "overview", [s1])
            await on_valkey(client, s1)
            await client.execute_command("CLIENT", "KILL", "TYPE", "pubsub")
            assert await close_code(ws) == 1011


async def test_an_os_error_while_reading_valkey_closes_1011(api, clock, socket_base, client, monkeypatch):
    async def reset(self, **kwargs):
        raise ConnectionResetError("reset by peer")

    s1 = (await make_server((await make_group("staging")).id, "web-1")).id
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            monkeypatch.setattr("valkey.asyncio.client.PubSub.get_message", reset)
            await ws.send(json.dumps({"type": "subscribe", "view": "overview", "server_ids": [str(s1)]}))
            assert await close_code(ws) == 1011

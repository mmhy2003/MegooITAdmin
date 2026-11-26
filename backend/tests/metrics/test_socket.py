"""WS /api/ws/metrics: a person subscribes to the servers on their screen, gets the live samples of those they see
in the view they asked for, and is told which ones they do not see."""

import asyncio
import json
import uuid
from datetime import UTC, datetime

import pytest
from auth_helpers import EMAIL, PASSWORD, add_grant, events, make_group, make_server, make_user, signed_in
from socket_helpers import close_code, connect, serving
from websockets.exceptions import InvalidStatus

from app.auth.sessions import COOKIE
from app.core.valkey import valkey_client
from app.main import create_app
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

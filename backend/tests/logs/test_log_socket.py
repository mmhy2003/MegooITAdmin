"""WS /api/ws/logs: a person subscribes to log sources, the socket asks the logs worker (a fake one here) to open those
they may read, and sends each source's backlog first, then its new lines without a gap or a repeat. Every refusal is
told, an access.denied is recorded once per server, and each opened stream names the person, server and sources."""

import json
import uuid

import pytest
from auth_helpers import add_grant, events, make_group, make_server, signed_in
from collector_helpers import eventually
from logs_helpers import FakeWorker, add_pattern, log_file, receive, subscribe, text_line, viewers
from socket_helpers import close_code, connect, serving
from websockets.exceptions import InvalidStatus

from app.auth.sessions import COOKIE
from app.core.valkey import valkey_client
from app.logs.protocol import Lines, Opened, Skipped, encode, viewer_channel
from app.logs.sources import SOURCES, describe, source_key
from app.main import create_app

PATH = "/api/ws/logs"
ROUTE = "WS /api/ws/logs"
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


async def staging_server(name: str = "web-1"):
    group = await make_group("staging")
    await add_pattern(group.id, PATTERN)
    return group, await make_server(group.id, name)


def file_source(server_id, path: str) -> dict:
    return {"kind": "file", "server_id": str(server_id), "path": path}


def journal_source(server_id, unit: str | None = None) -> dict:
    return {"kind": "journal", "server_id": str(server_id), "unit": unit}


def key_of(source: dict) -> str:
    return source_key(SOURCES.validate_python(source))


def described(source: dict) -> dict:
    return describe(SOURCES.validate_python(source))


async def no_viewers(client, key: str) -> bool:
    return await viewers(client, key) == 0


async def test_no_cookie_closes_4401(socket_base):
    async with connect(socket_base, PATH) as ws:
        assert await close_code(ws) == 4401


async def test_a_foreign_origin_gets_403(api, clock, socket_base):
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        with pytest.raises(InvalidStatus) as refused:
            async with connect(socket_base, PATH, browser.cookies.get(COOKIE), origin="http://evil.example"):
                pass
    assert refused.value.response.status_code == 403


async def test_subscribe_opens_a_source_and_sends_the_backlog_first(api, clock, socket_base, client, worker):
    _, server = await staging_server()
    source = file_source(server.id, log_file("access"))
    key = key_of(source)
    worker.backlogs[key] = ([text_line(1, "a"), text_line(2, "b")], 2)
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            reply = await subscribe(ws, [source])
            assert reply == {"type": "subscribed", "sources": [{"id": key, "source": described(source)}], "denied": []}
            assert await receive(ws) == {
                "type": "lines", "source": key, "lines": [text_line(1, "a"), text_line(2, "b")], "backlog": True
            }
            assert await viewers(client, key) == 1
            [request] = worker.requests
            assert request.source == SOURCES.validate_python(source)

            await worker.publish(key, Lines(type="lines", lines=[text_line(3, "c")]))
            assert await receive(ws) == {"type": "lines", "source": key, "lines": [text_line(3, "c")]}


async def test_lines_held_before_opened_are_sent_once_without_a_gap(api, clock, socket_base, client):
    _, server = await staging_server()
    source = file_source(server.id, log_file("held"))
    key = key_of(source)
    async with FakeWorker(client, answer=False) as worker, signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await ws.send(json.dumps({"type": "subscribe", "sources": [source]}))
            await eventually(lambda: worker.requests, timeout=5, every=0.02)
            [request] = worker.requests
            await worker.publish(key, Lines(type="lines", lines=[text_line(2, "b"), text_line(3, "c")]))
            await worker.publish(key, Lines(type="lines", lines=[text_line(4, "d")]))
            backlog = [text_line(1, "a"), text_line(2, "b"), text_line(3, "c")]
            opened = Opened(type="opened", request_id=request.request_id, key=key, run_id=worker.run_id, lines=backlog,
                            last_seq=3)
            await client.publish(viewer_channel(request.socket_id), encode(opened))

            assert (await receive(ws))["type"] == "subscribed"
            assert await receive(ws) == {"type": "lines", "source": key, "lines": backlog, "backlog": True}
            assert await receive(ws) == {"type": "lines", "source": key, "lines": [text_line(4, "d")]}
            await worker.publish(key, Lines(type="lines", lines=[text_line(5, "e")]))
            assert await receive(ws) == {"type": "lines", "source": key, "lines": [text_line(5, "e")]}


async def test_skipped_is_forwarded(api, clock, socket_base, worker):
    _, server = await staging_server()
    source = file_source(server.id, log_file("noisy"))
    key = key_of(source)
    worker.backlogs[key] = ([text_line(1, "a")], 1)
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            await subscribe(ws, [source])
            assert (await receive(ws))["backlog"] is True
            await worker.publish(key, Skipped(type="skipped", count=5, after_seq=1))
            await worker.publish(key, Lines(type="lines", lines=[text_line(2, "b")]))
            assert await receive(ws) == {"type": "skipped", "source": key, "count": 5}
            assert await receive(ws) == {"type": "lines", "source": key, "lines": [text_line(2, "b")]}


async def test_a_server_the_person_does_not_see_is_not_found_and_recorded_once(api, clock, socket_base, worker):
    staging, _ = await staging_server()
    production = await make_group("production")
    hidden = await make_server(production.id, "db-1")
    asked = [journal_source(hidden.id), journal_source(uuid.uuid4())]
    async with signed_in(api, clock, OPERATOR) as (otto, browser):
        await add_grant(otto.id, staging.id, "operator")
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            for _ in range(2):
                reply = await subscribe(ws, asked)
                assert reply == {
                    "type": "subscribed",
                    "sources": [],
                    "denied": [{"source": described(source), "reason": "not_found"} for source in asked],
                }
    [event] = await events("access.denied")
    assert event.result_detail == {"required": "group", "route": ROUTE, "server_ids": [str(hidden.id)]}
    assert worker.requests == []


@pytest.mark.parametrize("who", ["operator", "auditor"])
async def test_without_view_logs_is_forbidden(api, clock, socket_base, worker, who):
    group, server = await staging_server()
    asked = [journal_source(server.id, "nginx.service"), journal_source(server.id, "ssh.service")]
    async with signed_in(api, clock, OPERATOR, "auditor" if who == "auditor" else None) as (person, browser):
        if who == "operator":
            await add_grant(person.id, group.id, "operator", view_logs=False)
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            for _ in range(2):
                reply = await subscribe(ws, asked)
                assert reply["sources"] == []
                assert reply["denied"] == [{"source": described(source), "reason": "forbidden"} for source in asked]
    [event] = await events("access.denied")
    assert (event.actor_id, event.result) == (str(person.id), "failure")
    assert (event.target_type, event.target_id, event.target_name) == ("server", str(server.id), "web-1")
    assert event.context == {"server_group_id": str(group.id)}
    assert event.result_detail == {"required": "view_logs", "route": ROUTE}
    assert worker.requests == []


async def test_a_path_outside_the_allowlist_is_not_allowed(api, clock, socket_base, worker):
    group, server = await staging_server()
    asked = [file_source(server.id, "/var/log/secret.log"), file_source(server.id, "/etc/shadow")]
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            reply = await subscribe(ws, asked)
            assert reply["denied"] == [{"source": described(source), "reason": "not_allowed"} for source in asked]
            await subscribe(ws, asked)
    [event] = await events("access.denied")
    assert (event.target_id, event.context) == (str(server.id), {"server_group_id": str(group.id)})
    assert event.result_detail == {"required": "log_file_allowlist", "route": ROUTE, "path": "/var/log/secret.log"}
    assert worker.requests == []


async def test_a_worker_refusal_is_denied_and_closed(api, clock, socket_base, client, worker):
    _, server = await staging_server()
    source = file_source(server.id, log_file("refused"))
    key = key_of(source)
    worker.refusals[key] = "too_many_sources"
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            reply = await subscribe(ws, [source])
            assert reply == {
                "type": "subscribed",
                "sources": [],
                "denied": [{"source": described(source), "reason": "too_many_sources"}],
            }
            await eventually(lambda: no_viewers(client, key), timeout=5, every=0.02)
    [opened] = await events("logs.stream_opened")
    [closed] = await events("logs.stream_closed")
    assert closed.target_id == opened.target_id == str(server.id)
    assert closed.result_detail == {"sources": [described(source)], "duration_seconds": 0, "reason": "too_many_sources"}


async def test_stream_opened_names_the_person_server_and_sources(api, clock, socket_base, worker):
    group, server = await staging_server()
    other = await make_server(group.id, "web-2")
    journal, file = journal_source(server.id, "nginx.service"), file_source(server.id, log_file("named"))
    elsewhere = journal_source(other.id)
    async with signed_in(api, clock, OWNER, "owner") as (owner, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            reply = await subscribe(ws, [journal, file, elsewhere])
            assert reply["denied"] == []
            assert [one["id"] for one in reply["sources"]] == sorted(key_of(s) for s in [journal, file, elsewhere])
    opened = {event.target_id: event for event in await events("logs.stream_opened")}
    assert set(opened) == {str(server.id), str(other.id)}
    first = opened[str(server.id)]
    assert (first.actor_type, first.actor_id, first.actor_name) == ("human", str(owner.id), "owner")
    assert (first.target_type, first.target_name, first.result) == ("server", "web-1", "success")
    assert first.context == {"server_group_id": str(group.id)}
    assert first.result_detail == {"sources": [described(s) for s in sorted([journal, file], key=key_of)]}
    assert (first.auth_method, first.mfa) == ("password", True)
    assert opened[str(other.id)].result_detail == {"sources": [described(elsewhere)]}


async def test_an_invalid_message_gets_an_error_and_the_socket_stays_open(api, clock, socket_base, worker):
    _, server = await staging_server()
    too_many = [journal_source(server.id, f"unit-{n}.service") for n in range(17)]
    async with signed_in(api, clock, OWNER, "owner") as (_, browser):
        async with connect(socket_base, PATH, browser.cookies.get(COOKIE)) as ws:
            for text in [
                "nope",
                json.dumps({"type": "subscribe", "sources": too_many}),
                json.dumps({"type": "subscribe", "sources": [], "pad": "x" * 16_384}),
                json.dumps({"type": "subscribe", "sources": [journal_source(server.id, "-bad unit")]}),
            ]:
                await ws.send(text)
                assert await receive(ws) == {"type": "error", "detail": "invalid_message"}
            assert (await subscribe(ws, [journal_source(server.id)]))["denied"] == []

"""One server's stream against the fake server: samples published and written, reconnects after a broken session,
unreachable after a silence, refused accounts and changed host keys, and a database or Valkey that is down."""

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from valkey.asyncio import from_url

from app.collector.stream import Publisher, Stream, Target
from app.collector.writer import Writer
from app.core.valkey import valkey_client
from app.inventory.models import Server
from app.metrics.fanout import subscribe
from app.metrics.samples import Reading, Sample
from auth_helpers import events
from collector_helpers import FAST, eventually, metric_rows, parts, pinned_server, status_of, streaming
from conftest import owner_session

DOWN_URL = "postgresql+asyncpg://x:y@127.0.0.1:1/down_test"
LINE = (
    b'{"v":1,"uptime":12345.67,"load":[0.5,0.25,0.125],"cpu":[["cpu",100,0,50,800,50,0,0,0]],'
    b'"mem":{"total":8000000,"available":6000000,"swap_total":1000000,"swap_free":750000},'
    b'"net":[["eth0",1000,2000]],"disk":[["sda",0,0,0]],"fs":[["/",100000,40000,60000,1000,250]]}'
)


@pytest.fixture
async def valkey():
    client = valkey_client()
    yield client
    await client.aclose()


@pytest.fixture
async def down_sessions():
    engine = create_async_engine(DOWN_URL, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def stream_of(server: Server, publisher: Publisher, writer: Writer, status) -> Stream:
    return Stream(Target.of(server), publisher=publisher, writer=writer, status=status, timings=FAST)


async def test_samples_reach_a_subscriber_and_the_metrics_table(clean_auth, collector_sessions, fake_server, valkey):
    server = await pinned_server(fake_server, "stream-1")
    publisher, writer, status = parts(collector_sessions, valkey)
    stream = stream_of(server, publisher, writer, status)

    async with subscribe(valkey, [server.id]) as samples, streaming(stream, writer):
        sample = await asyncio.wait_for(anext(samples), 10)
        assert sample.server_id == server.id
        await eventually(lambda: metric_rows(server.id))
        assert await status_of(server.id) == ("reachable", None)


async def test_a_killed_ssh_session_reconnects(clean_auth, collector_sessions, fake_server, valkey):
    server = await pinned_server(fake_server, "stream-2")
    publisher, writer, status = parts(collector_sessions, valkey)
    stream = stream_of(server, publisher, writer, status)

    async with subscribe(valkey, [server.id]) as samples, streaming(stream, writer):
        await asyncio.wait_for(anext(samples), 10)
        before = await asyncio.to_thread(fake_server.sign_ins)
        await asyncio.to_thread(fake_server.kill_sessions)

        await eventually(lambda: asyncio.to_thread(lambda: fake_server.sign_ins() > before))
        after = stream.samples
        await eventually(lambda: stream.samples > after)


async def test_a_paused_server_is_unreachable_with_no_samples_and_comes_back(
    clean_auth, collector_sessions, fake_server
):
    server = await pinned_server(fake_server, "stream-3")
    publisher, writer, status = parts(collector_sessions)
    stream = stream_of(server, publisher, writer, status)

    async with streaming(stream, writer):
        await eventually(lambda: _is(server.id, ("reachable", None)))
        await asyncio.to_thread(fake_server.pause)
        try:
            await eventually(lambda: _is_not(server.id, ("reachable", None)), every=0.05)
            assert await status_of(server.id) == ("unreachable", "no_samples")
        finally:
            await asyncio.to_thread(fake_server.unpause)
        await eventually(lambda: _is(server.id, ("reachable", None)), timeout=30)


async def test_a_wrong_account_is_key_refused(clean_auth, collector_sessions, fake_server):
    server = await pinned_server(fake_server, "stream-4", username="megoo-unknown")
    publisher, writer, status = parts(collector_sessions)
    stream = stream_of(server, publisher, writer, status)

    async with streaming(stream, writer):
        await eventually(lambda: _is(server.id, ("unreachable", "key_refused")), timeout=10)


async def test_a_swapped_host_key_flags_the_server_once_and_stops(clean_auth, collector_sessions, fake_server):
    server = await pinned_server(fake_server, "stream-5")
    await asyncio.to_thread(fake_server.swap_host_key)
    publisher, writer, status = parts(collector_sessions)
    stream = stream_of(server, publisher, writer, status)

    await asyncio.wait_for(stream.run(), 15)

    (mismatch,) = await events("server.host_key_mismatch")
    assert (mismatch.actor_type, mismatch.actor_name) == ("system", "collector")
    async with owner_session() as session:
        row = (await session.execute(select(Server).where(Server.id == server.id))).scalar_one()
    assert row.host_key_changed_at is not None
    assert await status_of(server.id) == ("not_monitored", "host_key_changed")


async def test_samples_are_published_while_the_database_is_down(
    clean_auth, collector_sessions, fake_server, valkey, down_sessions
):
    server = await pinned_server(fake_server, "stream-6")
    publisher, _, status = parts(collector_sessions, valkey)
    writer = Writer(down_sessions)
    stream = stream_of(server, publisher, writer, status)

    async with subscribe(valkey, [server.id]) as samples, streaming(stream, writer):
        assert (await asyncio.wait_for(anext(samples), 10)).server_id == server.id
        assert writer.pending > 0


async def test_with_valkey_down_publish_returns_and_warns_once(caplog):
    down = from_url("valkey://127.0.0.1:1/0")
    publisher = Publisher(down)
    sample = Sample(time=datetime.now(UTC), server_id=uuid.uuid4(), readings=(Reading(metric="load.1m", value=0.5),))
    try:
        with caplog.at_level(logging.WARNING, logger="app.collector.stream"):
            started = time.monotonic()
            await publisher.publish(sample)
            await publisher.publish(sample)
            assert time.monotonic() - started < 3
    finally:
        await down.aclose()

    assert len([r for r in caplog.records if r.name == "app.collector.stream"]) == 1


async def test_a_line_that_does_not_parse_is_counted_and_never_logged(clean_auth, collector_sessions, caplog):
    publisher, writer, status = parts(collector_sessions)
    target = Target(uuid.uuid4(), "127.0.0.1", 22, "megoo", "ssh-ed25519 AAAA", 1)
    stream = Stream(target, publisher=publisher, writer=writer, status=status, timings=FAST)

    async def chunks():
        yield b"secret-text\n"
        yield LINE + b"\n"

    with caplog.at_level(logging.DEBUG):
        await stream._read(chunks())

    assert stream.bad_lines == 1
    assert stream.samples == 1
    assert writer.pending == 1
    assert "secret-text" not in caplog.text


async def _is(server_id: uuid.UUID, value: tuple[str, str | None]) -> bool:
    return await status_of(server_id) == value


async def _is_not(server_id: uuid.UUID, value: tuple[str, str | None]) -> bool:
    return await status_of(server_id) != value

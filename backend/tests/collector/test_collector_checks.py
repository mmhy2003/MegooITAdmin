"""A stream runs its server's slow checks beside the metrics loop, on a second channel of the same connection: every
check is recorded, a reconnect keeps the timetable, and neither a hung check nor a failing store stops the samples."""

import asyncio
import dataclasses

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.checks.models import Container, ServerCheck
from app.collector.checks import CHECKS, Check
from app.collector.checks.parse import CheckResult
from app.collector.checks.runner import Recorder
from app.collector.stream import Stream, Target
from app.inventory.models import Server
from app.metrics.models import Metric
from collector_helpers import FAST, eventually, parts, pinned_server, status_of, streaming
from conftest import owner_session

DOWN_URL = "postgresql+asyncpg://x:y@127.0.0.1:1/down_test"
FAST_CHECKS = [dataclasses.replace(check, every=2) for check in CHECKS]


@pytest.fixture
async def down_sessions():
    engine = create_async_engine(DOWN_URL, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def stream_of(server: Server, sessions, checks=FAST_CHECKS, recorder_sessions=None) -> tuple[Stream, object]:
    publisher, writer, status = parts(sessions)
    recorder = Recorder(recorder_sessions or sessions, publisher, writer)
    stream = Stream(
        Target.of(server),
        publisher=publisher,
        writer=writer,
        status=status,
        timings=FAST,
        recorder=recorder,
        checks=checks,
        first_delay=0,
    )
    return stream, writer


async def checks_of(server: Server) -> list[ServerCheck]:
    async with owner_session() as session:
        found = await session.scalars(select(ServerCheck).where(ServerCheck.server_id == server.id))
        return list(found.all())


async def containers_of(server: Server) -> list[str]:
    async with owner_session() as session:
        found = await session.scalars(select(Container.name).where(Container.server_id == server.id))
        return sorted(found.all())


async def has_metric(server: Server, metric: str) -> bool:
    async with owner_session() as session:
        count = select(func.count()).select_from(Metric).where(Metric.server_id == server.id, Metric.metric == metric)
        return (await session.execute(count)).scalar_one() > 0


async def test_a_stream_records_every_check_and_the_containers(clean_auth, collector_sessions, fake_server):
    server = await pinned_server(fake_server, "checks-1")
    stream, writer = stream_of(server, collector_sessions)

    async with streaming(stream, writer):
        await eventually(lambda: _count(server, 6), timeout=60)
        rows = await checks_of(server)
        assert sorted(row.kind for row in rows) == sorted(check.kind for check in CHECKS)
        assert all(row.status == "ok" for row in rows), [(row.kind, row.status) for row in rows]
        assert await containers_of(server) == sorted(["shop-web-1", "shop-db-1", "monitoring-grafana-1", "hello-adhoc"])
    assert await has_metric(server, "services.failed")


async def _count(server: Server, n: int) -> bool:
    return len(await checks_of(server)) >= n


async def test_a_reconnect_keeps_the_timetable(clean_auth, collector_sessions, fake_server):
    server = await pinned_server(fake_server, "checks-2")
    checks = [dataclasses.replace(check, every=3600) for check in CHECKS]
    stream, writer = stream_of(server, collector_sessions, checks=checks)

    async with streaming(stream, writer):
        await eventually(lambda: _count(server, 6), timeout=60)
        before = {row.kind: row.checked_at for row in await checks_of(server)}
        signed_in = await asyncio.to_thread(fake_server.sign_ins)
        await asyncio.to_thread(fake_server.kill_sessions)
        await eventually(lambda: asyncio.to_thread(lambda: fake_server.sign_ins() > signed_in))
        samples = stream.samples
        await eventually(lambda: stream.samples > samples)
        assert {row.kind: row.checked_at for row in await checks_of(server)} == before


class Nothing(CheckResult):
    pass


async def test_a_hung_check_does_not_stop_samples(clean_auth, collector_sessions, fake_server):
    server = await pinned_server(fake_server, "checks-3")
    hung = Check("services", 60, 30, b"exec sleep 20", lambda lines: Nothing())
    stream, writer = stream_of(server, collector_sessions, checks=[hung])

    try:
        async with streaming(stream, writer):
            await eventually(lambda: stream.samples > 0)
            samples = stream.samples
            for _ in range(int(2 * FAST.no_sample_after / 0.5)):
                await asyncio.sleep(0.5)
                assert await status_of(server.id) == ("reachable", None)
            assert stream.samples >= samples + 4  # one a second
    finally:
        # Closing the channel leaves the sleep running, and the script tests count leftover processes.
        await asyncio.to_thread(fake_server.exec, "pkill", "-u", "megoo", "-x", "sleep")


async def test_a_failing_store_does_not_stop_the_stream(clean_auth, collector_sessions, fake_server, down_sessions):
    server = await pinned_server(fake_server, "checks-4")
    stream, writer = stream_of(server, collector_sessions, recorder_sessions=down_sessions)

    async with streaming(stream, writer):
        await eventually(lambda: stream.samples > 0)
        samples = stream.samples
        for _ in range(int(2 * FAST.no_sample_after / 0.5)):
            await asyncio.sleep(0.5)
            assert await status_of(server.id) == ("reachable", None)
        assert stream.samples >= samples + 4  # one a second


async def test_the_checks_stop_with_the_stream(clean_auth, collector_sessions, fake_server):
    server = await pinned_server(fake_server, "checks-5")
    stream, writer = stream_of(server, collector_sessions)

    async with streaming(stream, writer):
        await eventually(lambda: _count(server, 1), timeout=60)

    def nothing_left() -> bool:
        return fake_server.exec("pgrep", "-u", "megoo", "-f", "^sh -s").stdout.strip() == ""

    await eventually(lambda: asyncio.to_thread(nothing_left), timeout=6)

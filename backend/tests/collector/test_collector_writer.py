"""The collector's metrics writer: one insert per batch, and during a database outage the newest samples wait in a
bounded buffer."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.collector.writer as writer_module
from app.collector.writer import Writer
from app.metrics.models import Metric
from app.metrics.samples import Reading, Sample
from collector_helpers import metric_rows
from conftest import owner_session

DOWN_URL = "postgresql+asyncpg://x:y@127.0.0.1:1/down_test"
START = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)
READINGS = (Reading(metric="load1", value=0.5), Reading(metric="disk.used_percent", instance="/var", value=81.0))


def sample(server_id: uuid.UUID, n: int) -> Sample:
    return Sample(time=START + timedelta(seconds=n), server_id=server_id, readings=READINGS)


async def times_of(server_id: uuid.UUID) -> list[datetime]:
    async with owner_session() as session:
        found = await session.execute(select(Metric.time).where(Metric.server_id == server_id).distinct())
        return sorted(found.scalars())


@pytest.fixture
async def down_sessions():
    engine = create_async_engine(DOWN_URL, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_a_batch_is_one_insert(clean_auth, collector_sessions, monkeypatch):
    calls = []
    real = writer_module.write_samples

    async def counting(session, samples):
        calls.append(len(samples))
        await real(session, samples)

    monkeypatch.setattr(writer_module, "write_samples", counting)
    server_id = uuid.uuid4()
    writer = Writer(collector_sessions)
    for n in range(3):
        writer.add(sample(server_id, n))

    assert await writer.flush() == 3

    assert calls == [3]
    assert writer.pending == 0
    assert await metric_rows(server_id) == 3 * len(READINGS)


async def test_a_sample_written_again_is_ignored(clean_auth, collector_sessions):
    # The collector's role may only INSERT into metrics: the duplicate must be skipped without needing SELECT.
    server_id = uuid.uuid4()
    writer = Writer(collector_sessions)
    writer.add(sample(server_id, 1))
    await writer.flush()

    writer.add(sample(server_id, 1))

    assert await writer.flush() == 1
    assert await metric_rows(server_id) == len(READINGS)


async def test_with_the_database_down_the_buffer_keeps_the_newest(
    clean_auth, collector_sessions, down_sessions, caplog
):
    server_id = uuid.uuid4()
    writer = Writer(down_sessions, max_samples=3)
    for n in range(1, 6):
        writer.add(sample(server_id, n))

    assert (writer.pending, writer.dropped) == (3, 2)
    assert await writer.flush() == 0
    assert await writer.flush() == 0
    assert (writer.pending, writer.dropped) == (3, 2)
    # One warning for the drops and one for the failed writes, not one per sample or per flush.
    assert len([r for r in caplog.records if r.name == "app.collector.writer"]) == 2

    writer.sessions = collector_sessions
    assert await writer.flush() == 3

    assert writer.pending == 0
    assert await times_of(server_id) == [START + timedelta(seconds=n) for n in (3, 4, 5)]


async def test_a_failed_batch_goes_back_before_what_arrived_meanwhile(collector_sessions, monkeypatch):
    server_id = uuid.uuid4()
    writer = Writer(collector_sessions, max_samples=3)

    async def failing(session, samples):
        writer.add(sample(server_id, 3))
        writer.add(sample(server_id, 4))
        raise OSError("connection reset")

    monkeypatch.setattr(writer_module, "write_samples", failing)
    writer.add(sample(server_id, 1))
    writer.add(sample(server_id, 2))

    assert await writer.flush() == 0

    assert (writer.pending, writer.dropped) == (3, 1)
    assert [s.time for s in writer._buffer] == [START + timedelta(seconds=n) for n in (2, 3, 4)]


async def test_flush_of_an_empty_buffer_does_nothing(collector_sessions, monkeypatch):
    calls = []

    async def counting(session, samples):
        calls.append(samples)

    monkeypatch.setattr(writer_module, "write_samples", counting)

    assert await Writer(collector_sessions).flush() == 0
    assert calls == []

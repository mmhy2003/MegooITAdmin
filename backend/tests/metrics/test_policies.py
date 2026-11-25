import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import owner_call, owner_session
from sqlalchemy import text

from app.core.db import SessionLocal
from app.metrics.samples import Reading, Sample
from app.metrics.store import Bucket, read_rollup, write_samples

pytestmark = pytest.mark.usefixtures("metrics_jobs_paused")


def _minute_ago(delta: timedelta) -> datetime:
    return (datetime.now(UTC) - delta).replace(second=0, microsecond=0)


async def _write(server_id: uuid.UUID, *points: tuple[datetime, float]) -> None:
    async with owner_session() as session:
        await write_samples(
            session,
            [Sample(time=t, server_id=server_id, readings=(Reading(metric="load1", value=v),)) for t, v in points],
        )
        await session.commit()


async def _refresh_1m(around: datetime) -> None:
    start, end = (around - timedelta(hours=1)).isoformat(), (around + timedelta(hours=1)).isoformat()
    await owner_call(f"CALL refresh_continuous_aggregate('metrics_1m', '{start}', '{end}')")


async def _run_job(proc_name: str) -> None:
    async with owner_session() as session:
        job_id = await session.scalar(
            text("SELECT job_id FROM timescaledb_information.jobs WHERE proc_name = :p AND hypertable_name = 'metrics'"),
            {"p": proc_name},
        )
    assert job_id is not None, proc_name
    await owner_call(f"CALL run_job({int(job_id)})")


async def _minute(server_id: uuid.UUID, minute: datetime) -> list[Bucket]:
    async with SessionLocal() as session:
        return await read_rollup(session, "1m", server_id, "load1", "", minute, minute + timedelta(minutes=1))


async def _raw_count(server_id: uuid.UUID) -> int:
    async with owner_session() as session:
        return await session.scalar(text("SELECT count(*) FROM metrics WHERE server_id = :id"), {"id": server_id})


async def test_retention_drops_raw_samples_older_than_48_hours_and_keeps_their_minutes():
    server_id, minute = uuid.uuid4(), _minute_ago(timedelta(days=4))
    await _write(server_id, (minute + timedelta(seconds=10), 1.0), (minute + timedelta(seconds=30), 3.0))
    await _refresh_1m(minute)
    await _run_job("policy_retention")
    assert await _raw_count(server_id) == 0
    assert await _minute(server_id, minute) == [Bucket(minute, 2.0, 1.0, 3.0, 2)]


async def test_compression_keeps_the_rollups_and_accepts_a_late_sample():
    server_id, minute = uuid.uuid4(), _minute_ago(timedelta(hours=13))
    await _write(server_id, (minute + timedelta(seconds=5), 5.0))
    await _refresh_1m(minute)
    assert await _minute(server_id, minute) == [Bucket(minute, 5.0, 5.0, 5.0, 1)]

    await _run_job("policy_compression")
    async with owner_session() as session:
        compressed = await session.scalar(
            text(
                "SELECT is_compressed FROM timescaledb_information.chunks WHERE hypertable_name = 'metrics'"
                " AND range_start <= :t AND range_end > :t"
            ),
            {"t": minute},
        )
    assert compressed is True
    assert await _minute(server_id, minute) == [Bucket(minute, 5.0, 5.0, 5.0, 1)]

    await _write(server_id, (minute + timedelta(seconds=25), 7.0))
    await _refresh_1m(minute)
    assert await _raw_count(server_id) == 2
    assert await _minute(server_id, minute) == [Bucket(minute, 6.0, 5.0, 7.0, 2)]

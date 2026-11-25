import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import owner_session
from sqlalchemy import text

from app.core.db import SessionLocal
from app.metrics.samples import Reading, Sample
from app.metrics.store import Bucket, read_rollup, write_samples

pytestmark = pytest.mark.usefixtures("database_at_head")


def _next_hour() -> datetime:
    # Above any refresh watermark: these rows can only be seen through the rollups' real-time part.
    return datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def _samples(server_id: uuid.UUID, hour: datetime) -> list[Sample]:
    def sample(offset: timedelta, value: float) -> Sample:
        return Sample(
            time=hour + offset,
            server_id=server_id,
            readings=(
                Reading(metric="cpu.used_percent", value=value),
                Reading(metric="disk.used_percent", instance="/var", value=value + 1),
            ),
        )

    return [sample(timedelta(seconds=0), 10.0), sample(timedelta(seconds=30), 20.0), sample(timedelta(minutes=1), 60.0)]


async def _write(samples: list[Sample]) -> None:
    async with owner_session() as session:
        await write_samples(session, samples)
        await session.commit()


async def _read(resolution, server_id, hour, metric="cpu.used_percent", instance="") -> list[Bucket]:
    async with SessionLocal() as session:
        return await read_rollup(session, resolution, server_id, metric, instance, hour, hour + timedelta(hours=1))


async def test_samples_are_read_back_as_1_minute_rollups():
    server_id, hour = uuid.uuid4(), _next_hour()
    await _write(_samples(server_id, hour))
    assert await _read("1m", server_id, hour) == [
        Bucket(hour, 15.0, 10.0, 20.0, 2),
        Bucket(hour + timedelta(minutes=1), 60.0, 60.0, 60.0, 1),
    ]


async def test_the_hourly_rollup_weights_each_minute_by_its_sample_count():
    server_id, hour = uuid.uuid4(), _next_hour()
    await _write(_samples(server_id, hour))
    # (10 + 20 + 60) / 3, not the average of the minutes (15 + 60) / 2.
    assert await _read("1h", server_id, hour) == [Bucket(hour, 30.0, 10.0, 60.0, 3)]


async def test_a_repeated_sample_changes_nothing():
    server_id, hour = uuid.uuid4(), _next_hour()
    await _write(_samples(server_id, hour))
    await _write(_samples(server_id, hour))
    async with owner_session() as session:
        count = await session.scalar(
            text("SELECT count(*) FROM metrics WHERE server_id = :id AND metric = 'cpu.used_percent'"), {"id": server_id}
        )
    assert count == 3
    assert await _read("1h", server_id, hour) == [Bucket(hour, 30.0, 10.0, 60.0, 3)]


async def test_readings_of_other_instances_and_metrics_stay_apart():
    server_id, hour = uuid.uuid4(), _next_hour()
    await _write(_samples(server_id, hour))
    assert await _read("1h", server_id, hour, "disk.used_percent", "/var") == [Bucket(hour, 31.0, 11.0, 61.0, 3)]
    assert await _read("1h", server_id, hour, "disk.used_percent", "") == []
    assert await _read("1h", uuid.uuid4(), hour) == []


async def test_an_unknown_resolution_is_refused():
    with pytest.raises(ValueError):
        await _read("5m", uuid.uuid4(), _next_hour())

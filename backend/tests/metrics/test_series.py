import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import owner_session

from app.core.db import SessionLocal
from app.metrics.ranges import RANGES
from app.metrics.samples import Reading, Sample
from app.metrics.store import Series, read_series, write_samples

pytestmark = pytest.mark.usefixtures("database_at_head")


def _next_hour() -> datetime:
    # Above any refresh watermark: these rows can only be seen through the rollups' real-time part.
    return datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def _next_even_hour() -> datetime:
    # 2-hour steps start at even hours UTC; also before 22:00, so the next hour falls on the same day.
    hour = _next_hour()
    while hour.hour % 2 or hour.hour >= 22:
        hour += timedelta(hours=1)
    return hour


def _next_day() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


async def _write(server_id: uuid.UUID, points: list[tuple[datetime, float]], metric="cpu.used_percent", instance=""):
    samples = [
        Sample(time=time, server_id=server_id, readings=(Reading(metric=metric, instance=instance, value=value),))
        for time, value in points
    ]
    async with owner_session() as session:
        await write_samples(session, samples)
        await session.commit()


async def _read(server_id, range_name, now, metrics=("cpu.used_percent",)) -> list[Series]:
    async with SessionLocal() as session:
        return await read_series(session, server_id, list(metrics), RANGES[range_name], now=now)


async def test_live_returns_every_sample_of_the_last_15_minutes():
    server_id, now = uuid.uuid4(), _next_hour() + timedelta(minutes=30)
    for instance in ("cpu0", ""):
        await _write(
            server_id,
            [(now - timedelta(minutes=20), 1.0), (now - timedelta(minutes=10), 2.0), (now - timedelta(seconds=5), 3.0)],
            instance=instance,
        )
    times = [now - timedelta(minutes=10), now - timedelta(seconds=5)]
    assert await _read(server_id, "live", now) == [
        Series("cpu.used_percent", "", times, [2.0, 3.0], [None, None], [None, None]),
        Series("cpu.used_percent", "cpu0", times, [2.0, 3.0], [None, None], [None, None]),
    ]


async def test_1h_averages_10_second_steps_with_lows_and_highs():
    server_id, base = uuid.uuid4(), _next_hour()
    seconds = [(0, 10.0), (3, 20.0), (7, 60.0), (12, 5.0)]
    await _write(server_id, [(base + timedelta(seconds=s), v) for s, v in seconds])
    assert await _read(server_id, "1h", base + timedelta(minutes=1)) == [
        Series("cpu.used_percent", "", [base, base + timedelta(seconds=10)], [30.0, 5.0], [10.0, 5.0], [60.0, 5.0])
    ]


async def test_6h_and_24h_read_metrics_1m_by_1_and_5_minutes():
    server_id, base = uuid.uuid4(), _next_hour()
    minutes = [(0, 10.0), (0.5, 20.0), (1, 60.0), (5, 7.0)]
    await _write(server_id, [(base + timedelta(minutes=m), v) for m, v in minutes])
    now = base + timedelta(minutes=6)
    at = [base, base + timedelta(minutes=1), base + timedelta(minutes=5)]
    assert await _read(server_id, "6h", now) == [
        Series("cpu.used_percent", "", at, [15.0, 60.0, 7.0], [10.0, 60.0, 7.0], [20.0, 60.0, 7.0])
    ]
    # (10 + 20 + 60) / 3, not the average of the minutes (15 + 60) / 2.
    assert await _read(server_id, "24h", now) == [
        Series("cpu.used_percent", "", [base, base + timedelta(minutes=5)], [30.0, 7.0], [10.0, 7.0], [60.0, 7.0])
    ]


async def test_7d_steps_are_30_minutes():
    server_id, base = uuid.uuid4(), _next_hour()
    await _write(server_id, [(base, 10.0), (base + timedelta(minutes=10), 20.0), (base + timedelta(minutes=40), 6.0)])
    assert await _read(server_id, "7d", base + timedelta(hours=1)) == [
        Series("cpu.used_percent", "", [base, base + timedelta(minutes=30)], [15.0, 6.0], [10.0, 6.0], [20.0, 6.0])
    ]


async def test_30d_and_1y_read_metrics_1h_weighted():
    server_id, hour = uuid.uuid4(), _next_even_hour()
    await _write(
        server_id,
        [(hour, 10.0), (hour + timedelta(minutes=30), 20.0), (hour + timedelta(hours=1, minutes=10), 60.0)],
    )
    now = hour + timedelta(hours=2)
    assert await _read(server_id, "30d", now) == [Series("cpu.used_percent", "", [hour], [30.0], [10.0], [60.0])]
    day = hour.replace(hour=0)
    assert await _read(server_id, "1y", now) == [Series("cpu.used_percent", "", [day], [30.0], [10.0], [60.0])]


async def test_1_day_steps_are_cut_at_midnight_utc():
    server_id, day = uuid.uuid4(), _next_day()
    next_day = day + timedelta(days=1)
    await _write(server_id, [(next_day - timedelta(minutes=30), 4.0), (next_day + timedelta(minutes=30), 8.0)])
    assert await _read(server_id, "1y", next_day + timedelta(hours=1)) == [
        Series("cpu.used_percent", "", [day, next_day], [4.0, 8.0], [4.0, 8.0], [4.0, 8.0])
    ]


async def test_a_step_without_samples_is_left_out():
    server_id, base = uuid.uuid4(), _next_hour()
    await _write(server_id, [(base, 1.0), (base + timedelta(seconds=20), 3.0)])
    series = await _read(server_id, "1h", base + timedelta(minutes=1))
    assert [s.time for s in series] == [[base, base + timedelta(seconds=20)]]


async def test_only_the_asked_server_and_metrics():
    server_id, other, base = uuid.uuid4(), uuid.uuid4(), _next_hour()
    await _write(server_id, [(base, 1.0)], metric="mem.used_percent")
    await _write(server_id, [(base, 2.0)], metric="disk.used_percent", instance="/var")
    await _write(server_id, [(base, 3.0)], metric="load.1m")
    await _write(other, [(base, 4.0)], metric="mem.used_percent")
    series = await _read(server_id, "live", base + timedelta(minutes=1), ("mem.used_percent", "disk.used_percent"))
    assert [(s.metric, s.instance, s.avg) for s in series] == [
        ("disk.used_percent", "/var", [2.0]),
        ("mem.used_percent", "", [1.0]),
    ]

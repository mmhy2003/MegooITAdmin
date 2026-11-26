import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import owner_session

from app.core.db import SessionLocal
from app.metrics.overview import Disk, Overview
from app.metrics.samples import Reading, Sample
from app.metrics.store import TREND_SLOTS, TREND_STEP, ServerOverview, Trend, read_overview, write_samples

pytestmark = pytest.mark.usefixtures("database_at_head")


def _now() -> datetime:
    # In the future, so no other test's rows are in the window; 2.5 s into a trend slot.
    hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return hour + timedelta(minutes=30, seconds=2, milliseconds=500)


def _start(now: datetime) -> datetime:
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - epoch % 5, UTC) - 59 * TREND_STEP


async def _write(server_id: uuid.UUID, time: datetime, *readings: tuple[str, str, float]) -> None:
    sample = Sample(
        time=time,
        server_id=server_id,
        readings=tuple(Reading(metric=metric, instance=instance, value=value) for metric, instance, value in readings),
    )
    async with owner_session() as session:
        await write_samples(session, [sample])
        await session.commit()


async def _read(server_ids, now) -> dict[uuid.UUID, ServerOverview]:
    async with SessionLocal() as session:
        return await read_overview(session, server_ids, now=now)


def _empty(server_id: uuid.UUID) -> Overview:
    return Overview(server_id, None, None, None, None, None, None, None)


async def test_the_newest_values_of_the_last_5_minutes():
    server_id, now = uuid.uuid4(), _now()
    await _write(
        server_id,
        now - timedelta(seconds=20),
        ("cpu.used_percent", "", 10.0),
        ("mem.used_percent", "", 50.0),
        ("load.1m", "", 1.5),
        ("disk.used_percent", "/", 40.0),
        ("net.rx_bytes_per_sec", "eth0", 100.0),
    )
    await _write(
        server_id,
        now - timedelta(seconds=5),
        ("cpu.used_percent", "", 20.0),
        ("mem.used_percent", "", 55.0),
        ("disk.used_percent", "/", 41.0),
        ("disk.used_percent", "/var", 85.0),
        ("net.rx_bytes_per_sec", "eth0", 200.0),
        ("net.rx_bytes_per_sec", "eth1", 50.0),
        ("net.tx_bytes_per_sec", "eth0", 5.0),
    )
    result = await _read([server_id], now)
    assert result[server_id].overview == Overview(
        server_id, now - timedelta(seconds=5), 20.0, 55.0, 1.5, Disk("/var", 85.0), 250.0, 5.0
    )


async def test_older_than_5_minutes_is_not_newest():
    server_id, now = uuid.uuid4(), _now()
    await _write(server_id, now - timedelta(minutes=6), ("cpu.used_percent", "", 10.0), ("disk.used_percent", "/", 40.0))
    assert (await _read([server_id], now))[server_id].overview == _empty(server_id)


async def test_every_asked_server_has_an_entry():
    server_id, now = uuid.uuid4(), _now()
    assert await _read([server_id], now) == {
        server_id: ServerOverview(_empty(server_id), Trend(_start(now), [None] * 60, [None] * 60))
    }
    assert await _read([], now) == {}


async def test_the_trend_has_60_five_second_averages():
    server_id, now = uuid.uuid4(), _now()
    start = _start(now)
    last = start + 59 * TREND_STEP
    await _write(server_id, last, ("cpu.used_percent", "", 10.0), ("mem.used_percent", "", 40.0))
    await _write(server_id, last + timedelta(seconds=2), ("cpu.used_percent", "", 30.0), ("mem.used_percent", "", 60.0))
    await _write(server_id, start + timedelta(seconds=1), ("cpu.used_percent", "", 7.0), ("mem.used_percent", "", 8.0))
    await _write(server_id, start - timedelta(seconds=1), ("cpu.used_percent", "", 99.0), ("mem.used_percent", "", 99.0))
    trend = (await _read([server_id], now))[server_id].trend
    assert trend.start == start
    assert len(trend.cpu) == len(trend.mem) == TREND_SLOTS == 60
    assert trend.cpu == [7.0] + [None] * 58 + [20.0]
    assert trend.mem == [8.0] + [None] * 58 + [50.0]


async def test_only_instance_empty_counts_for_the_cpu_trend():
    server_id, now = uuid.uuid4(), _now()
    last = _start(now) + 59 * TREND_STEP
    await _write(server_id, last, ("cpu.used_percent", "", 10.0), ("cpu.used_percent", "cpu0", 90.0))
    assert (await _read([server_id], now))[server_id].trend.cpu[59] == 10.0


async def test_several_servers_in_one_read():
    a, b, now = uuid.uuid4(), uuid.uuid4(), _now()
    await _write(a, now - timedelta(seconds=2), ("cpu.used_percent", "", 10.0), ("mem.used_percent", "", 20.0))
    await _write(b, now - timedelta(seconds=1), ("cpu.used_percent", "", 30.0), ("mem.used_percent", "", 40.0))
    result = await _read([a, b], now)
    assert set(result) == {a, b}
    assert (result[a].overview.cpu, result[a].overview.mem) == (10.0, 20.0)
    assert (result[b].overview.cpu, result[b].overview.mem) == (30.0, 40.0)
    assert result[a].trend.cpu[59] == 10.0
    assert result[b].trend.mem[59] == 40.0

"""Writing samples to the metrics hypertable and reading them back as rollups or as the series of a chart range."""

import itertools
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics.models import Metric, metrics_1h, metrics_1m
from app.metrics.overview import OVERVIEW_METRICS, Overview, summarize
from app.metrics.ranges import Range
from app.metrics.samples import Reading, Sample

Resolution = Literal["1m", "1h"]

_ROLLUPS = {"1m": metrics_1m, "1h": metrics_1h}

TREND_SLOTS = 60
TREND_STEP = timedelta(seconds=5)
OVERVIEW_WINDOW = timedelta(minutes=5)

_TREND_METRICS = {"cpu.used_percent": "cpu", "mem.used_percent": "mem"}


@dataclass(frozen=True)
class Bucket:
    bucket: datetime
    avg_value: float
    min_value: float
    max_value: float
    samples: int


@dataclass(frozen=True)
class Series:
    metric: str
    instance: str
    time: list[datetime]
    avg: list[float]
    min: list[float | None]  # None for live, which returns every sample
    max: list[float | None]


@dataclass(frozen=True)
class Trend:
    start: datetime  # the first slot: time_bucket(5 s, now) - 59 * 5 s
    cpu: list[float | None]  # 60 averages of cpu.used_percent ""
    mem: list[float | None]  # 60 averages of mem.used_percent


@dataclass(frozen=True)
class ServerOverview:
    overview: Overview  # time None when no sample in the last 5 minutes
    trend: Trend


async def write_samples(session: AsyncSession, samples: Iterable[Sample]) -> None:
    """Inserts one row per reading in one statement. A repeated reading is ignored. The caller commits."""
    rows = [
        {
            "time": sample.time,
            "server_id": sample.server_id,
            "metric": reading.metric,
            "instance": reading.instance,
            "value": reading.value,
        }
        for sample in samples
        for reading in sample.readings
    ]
    if not rows:
        return
    # No conflict target: naming one needs SELECT on the table, which the collector's role does not have. The
    # primary key is the table's only unique constraint, so this ignores the same rows.
    await session.execute(postgresql.insert(Metric).on_conflict_do_nothing(), rows)


async def read_rollup(
    session: AsyncSession,
    resolution: Resolution,
    server_id: uuid.UUID,
    metric: str,
    instance: str,
    start: datetime,
    end: datetime,
) -> list[Bucket]:
    """The buckets of one series with start <= bucket < end, oldest first."""
    rollup = _ROLLUPS.get(resolution)
    if rollup is None:
        raise ValueError(f"Unknown resolution {resolution!r}: expected one of {', '.join(_ROLLUPS)}")
    c = rollup.c
    rows = await session.execute(
        select(c.bucket, c.avg_value, c.min_value, c.max_value, c.samples)
        .where(
            c.server_id == server_id,
            c.metric == metric,
            c.instance == instance,
            c.bucket >= start,
            c.bucket < end,
        )
        .order_by(c.bucket)
    )
    return [Bucket(*row) for row in rows]


async def read_series(
    session: AsyncSession, server_id: uuid.UUID, metrics: Sequence[str], range_: Range, *, now: datetime
) -> list[Series]:
    """Every instance of each metric with now - window <= time < now, sorted by (metric, instance), oldest first.
    A step without samples is left out."""
    start = now - range_.window
    if range_.source == "raw":
        m = Metric
        where = (m.server_id == server_id, m.metric.in_(metrics), m.time >= start, m.time < now)
        if range_.step is None:
            query = select(m.metric, m.instance, m.time.label("t"), m.value, None, None).where(*where)
        else:
            t = func.time_bucket(range_.step, m.time).label("t")
            query = (
                select(m.metric, m.instance, t, func.avg(m.value), func.min(m.value), func.max(m.value))
                .where(*where)
                .group_by(m.metric, m.instance, t)
            )
        query = query.order_by(m.metric, m.instance, "t")
    else:
        c = _ROLLUPS[range_.source].c
        t = func.time_bucket(range_.step, c.bucket).label("t")
        # Weighted by sample counts: a minute of two samples weighs twice a minute of one.
        avg = func.sum(c.avg_value * c.samples) / func.sum(c.samples)
        query = (
            select(c.metric, c.instance, t, avg, func.min(c.min_value), func.max(c.max_value))
            .where(c.server_id == server_id, c.metric.in_(metrics), c.bucket >= start, c.bucket < now)
            .group_by(c.metric, c.instance, t)
            .order_by(c.metric, c.instance, t)
        )
    series = []
    for (metric, instance), group in itertools.groupby(await session.execute(query), lambda row: row[:2]):
        rows = list(group)
        series.append(
            Series(
                metric=metric,
                instance=instance,
                time=[row[2] for row in rows],
                avg=[float(row[3]) for row in rows],  # the weighted sum may come back as a Decimal
                min=[row[4] for row in rows],
                max=[row[5] for row in rows],
            )
        )
    return series


def _trend_start(now: datetime) -> datetime:
    # time_bucket's 5-second buckets fall on multiples of 5 epoch seconds, so this agrees with the query.
    step = int(TREND_STEP.total_seconds())
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - epoch % step, UTC) - (TREND_SLOTS - 1) * TREND_STEP


async def read_overview(
    session: AsyncSession, server_ids: Sequence[uuid.UUID], *, now: datetime
) -> dict[uuid.UUID, ServerOverview]:
    """One entry per asked id, also for one without samples."""
    if not server_ids:
        return {}
    m = Metric
    newest = await session.execute(
        select(m.server_id, m.metric, m.instance, m.time, m.value)
        .ext(postgresql.distinct_on(m.server_id, m.metric, m.instance))
        .where(
            m.server_id.in_(server_ids),
            m.metric.in_(OVERVIEW_METRICS),
            m.time >= now - OVERVIEW_WINDOW,
            m.time < now,
        )
        .order_by(m.server_id, m.metric, m.instance, m.time.desc())
    )
    overviews = {}
    for server_id, group in itertools.groupby(newest, lambda row: row[0]):
        rows = list(group)
        readings = tuple(Reading(metric=metric, instance=instance, value=value) for _, metric, instance, _, value in rows)
        sample = Sample(time=max(row[3] for row in rows), server_id=server_id, readings=readings)
        overviews[server_id] = summarize(sample)

    start = _trend_start(now)
    slot = func.time_bucket(TREND_STEP, m.time).label("slot")
    trend_rows = await session.execute(
        select(m.server_id, m.metric, slot, func.avg(m.value))
        .where(
            m.server_id.in_(server_ids),
            m.instance == "",
            m.metric.in_(_TREND_METRICS),
            m.time >= start,
            m.time < start + TREND_SLOTS * TREND_STEP,
        )
        .group_by(m.server_id, m.metric, slot)
    )
    trends = {server_id: {"cpu": [None] * TREND_SLOTS, "mem": [None] * TREND_SLOTS} for server_id in server_ids}
    for server_id, metric, at, value in trend_rows:
        trends[server_id][_TREND_METRICS[metric]][int((at - start) / TREND_STEP)] = float(value)

    return {
        server_id: ServerOverview(
            overview=overviews.get(server_id) or Overview(server_id, None, None, None, None, None, None, None),
            trend=Trend(start=start, **trends[server_id]),
        )
        for server_id in server_ids
    }

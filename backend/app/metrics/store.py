"""Writing samples to the metrics hypertable and reading them back as rollups or as the series of a chart range."""

import itertools
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics.models import Metric, metrics_1h, metrics_1m
from app.metrics.ranges import Range
from app.metrics.samples import Sample

Resolution = Literal["1m", "1h"]

_ROLLUPS = {"1m": metrics_1m, "1h": metrics_1h}


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

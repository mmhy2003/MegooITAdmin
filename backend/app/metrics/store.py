"""Writing samples to the metrics hypertable and reading them back as 1-minute or 1-hour rollups."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics.models import Metric, metrics_1h, metrics_1m
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
    await session.execute(postgresql.insert(Metric).on_conflict_do_nothing(constraint="metrics_pkey"), rows)


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

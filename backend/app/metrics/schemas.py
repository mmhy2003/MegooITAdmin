"""The response bodies of /api/servers/{id}/metrics and /api/metrics/overview."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.metrics.ranges import RangeName


class SeriesOut(BaseModel):
    metric: str
    instance: str
    time: list[datetime]
    avg: list[float]
    min: list[float | None]
    max: list[float | None]


class SeriesAnswer(BaseModel):
    range: RangeName
    step_seconds: int | None  # None: every sample (live)
    start: datetime
    end: datetime
    series: list[SeriesOut]


class DiskOut(BaseModel):
    mount: str
    percent: float


class TrendOut(BaseModel):
    start: datetime
    cpu: list[float | None]
    mem: list[float | None]


class ServerOverviewOut(BaseModel):
    server_id: UUID
    time: datetime | None
    cpu: float | None
    mem: float | None
    load: float | None
    disk: DiskOut | None
    rx: float | None
    tx: float | None
    trend: TrendOut


class OverviewAnswer(BaseModel):
    servers: list[ServerOverviewOut]
    denied: list[UUID]

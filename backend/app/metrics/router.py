"""The routes /api/servers/{id}/metrics and /api/metrics/overview: everyone who sees a server reads its chart series;
the overview answers for the asked servers the person sees and records the others as one access.denied event."""

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.access.deps import CurrentAccess, require_group_visible
from app.access.servers import record_hidden, split_visible
from app.auth.deps import CurrentUser
from app.core.db import DbSession
from app.inventory.deps import group_of_server
from app.metrics.ranges import MAX_METRICS, RANGES, MetricName, RangeName
from app.metrics.schemas import DiskOut, OverviewAnswer, SeriesAnswer, SeriesOut, ServerOverviewOut, TrendOut
from app.metrics.store import read_overview, read_series

router = APIRouter()

visible = Depends(require_group_visible(group=group_of_server))
MAX_SERVERS = 200


@router.get("/servers/{server_id}/metrics", dependencies=[visible])
async def read_metrics(
    server_id: UUID,
    db: DbSession,
    range_: Annotated[RangeName, Query(alias="range")],
    metric: Annotated[list[MetricName], Query(min_length=1, max_length=MAX_METRICS)],
) -> SeriesAnswer:
    now = datetime.now(UTC)
    chosen = RANGES[range_]
    series = await read_series(db, server_id, sorted(set(metric)), chosen, now=now)
    return SeriesAnswer(
        range=range_,
        step_seconds=int(chosen.step.total_seconds()) if chosen.step else None,
        start=now - chosen.window,
        end=now,
        series=[SeriesOut(**asdict(line)) for line in series],
    )


@router.get("/metrics/overview")
async def read_overview_route(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    access: CurrentAccess,
    server_id: Annotated[list[UUID], Query(min_length=1, max_length=MAX_SERVERS)],
) -> OverviewAnswer:
    asked = list(dict.fromkeys(server_id))
    seen, hidden = await split_visible(db, access, asked)
    await record_hidden(request, user, "GET /api/metrics/overview", hidden)
    shown = [id_ for id_ in asked if id_ in seen]
    overviews = await read_overview(db, shown, now=datetime.now(UTC))
    servers = []
    for id_ in shown:
        overview, trend = overviews[id_].overview, overviews[id_].trend
        servers.append(
            ServerOverviewOut(
                server_id=id_,
                time=overview.time,
                cpu=overview.cpu,
                mem=overview.mem,
                load=overview.load,
                disk=DiskOut(mount=overview.disk.mount, percent=overview.disk.percent) if overview.disk else None,
                rx=overview.rx,
                tx=overview.tx,
                trend=TrendOut(start=trend.start, cpu=trend.cpu, mem=trend.mem),
            )
        )
    missing = set(asked) - seen - set(hidden)
    return OverviewAnswer(servers=servers, denied=sorted(set(hidden) | missing))

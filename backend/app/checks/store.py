"""Writing the last result of a check and the containers a listing saw, and reading them back for a server."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.checks.models import Container, Kind, SeenContainer, ServerCheck, Status

_RUNTIME = "docker"


async def write_check(
    session: AsyncSession,
    server_id: uuid.UUID,
    kind: Kind,
    status: Status,
    *,
    checked_at: datetime,
    data: dict[str, Any] | None,
) -> None:
    """Records a run. A run without data (any status but "ok") keeps the last good data and its time. The caller
    commits."""
    insert = postgresql.insert(ServerCheck).values(
        server_id=server_id,
        kind=kind,
        status=status,
        checked_at=checked_at,
        data=data,
        data_at=checked_at if data is not None else None,
    )
    excluded = insert.excluded
    await session.execute(
        insert.on_conflict_do_update(
            index_elements=[ServerCheck.server_id, ServerCheck.kind],
            set_={
                "status": excluded.status,
                "checked_at": excluded.checked_at,
                "data": func.coalesce(excluded.data, ServerCheck.data),
                "data_at": case((excluded.data.is_(None), ServerCheck.data_at), else_=excluded.data_at),
            },
        )
    )


async def replace_containers(
    session: AsyncSession, server_id: uuid.UUID, containers: Sequence[SeenContainer], *, seen_at: datetime
) -> None:
    """Makes the server's Docker rows the listing: adds and updates what it saw, keeping when each was first seen,
    and deletes the rest. The caller commits."""
    if containers:
        insert = postgresql.insert(Container).values(
            [
                {
                    "server_id": server_id,
                    "runtime": _RUNTIME,
                    "container_id": container.container_id,
                    "name": container.name,
                    "image": container.image,
                    "compose_project": container.compose_project,
                    "compose_service": container.compose_service,
                    "state": container.state,
                    "status": container.status,
                    "first_seen_at": seen_at,
                    "last_seen_at": seen_at,
                }
                for container in containers
            ]
        )
        excluded = insert.excluded
        await session.execute(
            insert.on_conflict_do_update(
                index_elements=[Container.server_id, Container.runtime, Container.container_id],
                set_={
                    column: excluded[column]
                    for column in (
                        "name",
                        "image",
                        "compose_project",
                        "compose_service",
                        "state",
                        "status",
                        "last_seen_at",
                    )
                },
            )
        )
    await session.execute(
        delete(Container).where(
            Container.server_id == server_id,
            Container.runtime == _RUNTIME,
            Container.last_seen_at != seen_at,
        )
    )


async def read_checks(session: AsyncSession, server_id: uuid.UUID) -> dict[str, ServerCheck]:
    """The server's last result of each check that has run, by kind."""
    rows = await session.scalars(select(ServerCheck).where(ServerCheck.server_id == server_id))
    return {check.kind: check for check in rows}


async def read_containers(session: AsyncSession, server_id: uuid.UUID) -> list[Container]:
    """The server's containers by Compose project, those without one last, then by name."""
    rows = await session.scalars(
        select(Container)
        .where(Container.server_id == server_id)
        .order_by(Container.compose_project.asc().nulls_last(), Container.name)
    )
    return list(rows)

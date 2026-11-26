"""Which of many asked servers a person sees, and the one event for those they do not.

A metrics socket and the overview read both name many servers at once, so a single route guard cannot answer
them: they keep the servers the person sees and record the others as one access.denied event. A socket has no
FastAPI route, so the route is given as text and the source comes from the connection."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from app.access.actions import ACCESS_DENIED
from app.access.permissions import Access
from app.audit import Event, Result, record_alone, source_of
from app.auth.models import User
from app.auth.service import actor_of
from app.inventory.models import Server


async def split_visible(
    db: AsyncSession, access: Access, server_ids: Iterable[UUID]
) -> tuple[frozenset[UUID], dict[UUID, UUID]]:
    """(the asked servers the person sees, {existing asked server they do not see: its group}). One query.
    An id that is in neither does not exist."""
    ids = set(server_ids)
    if not ids:
        return frozenset(), {}
    visible: set[UUID] = set()
    hidden: dict[UUID, UUID] = {}
    for server_id, group_id in await db.execute(select(Server.id, Server.server_group_id).where(Server.id.in_(ids))):
        if access.sees(group_id):
            visible.add(server_id)
        else:
            hidden[server_id] = group_id
    return frozenset(visible), hidden


async def record_hidden(connection: HTTPConnection, user: User, route: str, hidden: Iterable[UUID]) -> None:
    """One access.denied event (record_alone) for these servers; nothing when there are none."""
    server_ids = sorted(str(server_id) for server_id in hidden)
    if not server_ids:
        return
    await record_alone(
        Event(
            action=ACCESS_DENIED,
            actor=actor_of(user),
            result=Result.FAILURE,
            target=None,
            result_detail={"required": "group", "route": route, "server_ids": server_ids},
            source=source_of(connection, auth_method="password", mfa=True),
        )
    )

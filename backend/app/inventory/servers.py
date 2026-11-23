"""The servers each person sees, and what an Admin does with them in their groups, between the routes and the
tables."""

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.permissions import Access
from app.audit import Event, Target, changes, record
from app.auth.models import User
from app.auth.service import actor_of, auth_event
from app.core.db import flush_refusing
from app.inventory import actions
from app.inventory.models import Server, ServerGroup, ServerTag
from app.inventory.server_schemas import ServerIn, ServerOut

FIELDS = ("name", "address", "port", "os", "role", "connection_settings")

# The constraints a request that won the race past a check runs into.
REFUSALS = {
    "servers_name_key": (409, "server_name_taken"),
    "servers_server_group_id_fkey": (422, "unknown_group"),
}


def _fields(server: Server) -> dict[str, Any]:
    """The fields of a server its events compare."""
    return {field: getattr(server, field) for field in FIELDS}


def _target(server: Server) -> Target:
    return Target(type="server", id=str(server.id), name=server.name)


def _event(
    request: Request, user: User, action: str, server: Server, *, change: dict | None, detail: dict | None = None
) -> Event:
    """An event of the server, in the context of its group as it is after the change."""
    return auth_event(
        request,
        action,
        actor_of(user),
        mfa=True,
        target=_target(server),
        change=change,
        detail=detail,
        context={"server_group_id": str(server.server_group_id)},
    )


async def _tags_of(db: AsyncSession, server_ids: Iterable[UUID]) -> dict[UUID, list[str]]:
    """The tags of each server, sorted, in one query."""
    tags: dict[UUID, list[str]] = {}
    query = select(ServerTag.server_id, ServerTag.tag).where(ServerTag.server_id.in_(list(server_ids)))
    for server_id, tag in (await db.execute(query.order_by(ServerTag.tag))).all():
        tags.setdefault(server_id, []).append(tag)
    return tags


def _out(server: Server, group_name: str, tags: list[str], access: Access) -> ServerOut:
    return ServerOut(
        id=server.id,
        name=server.name,
        address=server.address,
        port=server.port,
        os=server.os,
        role=server.role,
        tags=tags,
        group_id=server.server_group_id,
        group_name=group_name,
        connection_settings=server.connection_settings,
        host_key=server.host_key,
        created_at=server.created_at,
        updated_at=server.updated_at,
        can_manage=access.manages(server.server_group_id),
    )


async def _check_name(db: AsyncSession, name: str, server_id: UUID | None = None) -> None:
    """Another server with the name, in any group and without regard to case: 409."""
    query = select(Server.id).where(func.lower(Server.name) == name.lower())
    if server_id is not None:
        query = query.where(Server.id != server_id)
    if await db.scalar(query) is not None:
        raise HTTPException(409, "server_name_taken")


async def _group(db: AsyncSession, group_id: UUID) -> ServerGroup:
    """The group a server goes into. Only an Owner gets past the guard with a group that does not exist: 422."""
    group = await db.scalar(select(ServerGroup).where(ServerGroup.id == group_id))
    if group is None:
        raise HTTPException(422, "unknown_group")
    return group


async def get_server(db: AsyncSession, access: Access, server_id: UUID) -> ServerOut:
    """One server. The route's guard has already answered 404 for a server the person does not see."""
    server, group_name = (
        await db.execute(
            select(Server, ServerGroup.name)
            .join(ServerGroup, ServerGroup.id == Server.server_group_id)
            .where(Server.id == server_id)
        )
    ).one()
    tags = await _tags_of(db, [server.id])
    return _out(server, group_name, tags.get(server.id, []), access)


async def create_server(db: AsyncSession, request: Request, user: User, access: Access, body: ServerIn) -> ServerOut:
    group = await _group(db, body.group_id)
    await _check_name(db, body.name)
    server = Server(
        server_group_id=group.id,
        name=body.name,
        address=body.address,
        port=body.port,
        os=body.os,
        role=body.role,
        connection_settings=body.connection_settings.model_dump(),
    )
    db.add(server)
    await flush_refusing(db, REFUSALS)
    db.add_all(ServerTag(server_id=server.id, tag=tag) for tag in body.tags)
    await db.flush()
    await db.refresh(server)
    # record() last: it holds the audit chain lock until the commit.
    after = _fields(server) | {"group": group.name, "tags": body.tags}
    await record(db, _event(request, user, actions.SERVER_CREATED, server, change=changes({}, after)))
    return _out(server, group.name, body.tags, access)

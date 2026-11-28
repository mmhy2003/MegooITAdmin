"""The log views people save, between the routes and the table: who reads a view, and how one is saved and listed.

A view names sources on one or more servers. A private view is its owner's alone. A shared view is listed for the
Owner, and for whoever reads every one of its servers for views: so nobody gets a view that half works.
"""

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.permissions import Access, Permission
from app.audit import Target, changes, record
from app.auth.models import User
from app.auth.service import actor_of, auth_event
from app.core.db import flush_unique
from app.inventory.models import Server
from app.logs import actions
from app.logs.models import LogView
from app.logs.schemas import LogViewIn, LogViewOut

MAX_VIEWS = 100


def reads_for_views(access: Access, server: Server | None) -> bool:
    """Whether the person follows the server's logs: it exists, runs Linux, and they hold View logs in its group."""
    return server is not None and server.os == "linux" and access.allows(Permission.VIEW_LOGS, server.server_group_id)


async def _servers(db: AsyncSession, server_ids: Iterable[UUID]) -> dict[UUID, Server]:
    """The asked servers that exist, by ID."""
    ids = list(set(server_ids))
    if not ids:
        return {}
    return {server.id: server for server in await db.scalars(select(Server).where(Server.id.in_(ids)))}


def _server_ids(view: LogView) -> list[UUID]:
    return [UUID(source["server_id"]) for source in view.sources]


def _fields(view: LogView) -> dict[str, Any]:
    """The fields an event compares, as stored."""
    return {"name": view.name, "shared": view.shared, "sources": view.sources, "settings": view.settings}


def _out(view: LogView, owner_name: str, user: User, access: Access) -> LogViewOut:
    is_mine = view.owner_id == user.id
    return LogViewOut(
        id=view.id,
        name=view.name,
        shared=view.shared,
        owner_name=owner_name,
        is_mine=is_mine,
        can_edit=is_mine or access.is_owner,
        sources=view.sources,
        settings=view.settings,
        updated_at=view.updated_at,
    )


async def _check_servers(db: AsyncSession, access: Access, body: LogViewIn) -> None:
    """A server that does not exist or is out of sight: 404. One the person does not read for views: 403."""
    servers = await _servers(db, (source.server_id for source in body.sources))
    found = [servers.get(source.server_id) for source in body.sources]
    if any(server is None or not access.sees(server.server_group_id) for server in found):
        raise HTTPException(404, "not_found")
    if not all(reads_for_views(access, server) for server in found):
        raise HTTPException(403, "forbidden")


async def list_views(db: AsyncSession, access: Access, user: User) -> list[LogViewOut]:
    """The person's own views and the shared views of others they read, by name without regard to case. The Owner
    gets every shared view; anyone else only those whose every server they read for views."""
    query = (
        select(LogView, User.name)
        .join(User, User.id == LogView.owner_id)
        .where(or_(LogView.owner_id == user.id, LogView.shared))
        .order_by(func.lower(LogView.name), LogView.id)
    )
    rows = (await db.execute(query)).all()
    if not access.is_owner:
        others = [view for view, _ in rows if view.owner_id != user.id]
        servers = await _servers(db, (server_id for view in others for server_id in _server_ids(view)))
        rows = [
            (view, name)
            for view, name in rows
            if view.owner_id == user.id or all(reads_for_views(access, servers.get(i)) for i in _server_ids(view))
        ]
    return [_out(view, name, user, access) for view, name in rows]


async def create_view(db: AsyncSession, request: Request, user: User, access: Access, body: LogViewIn) -> LogViewOut:
    """Saves a view of the person. A server out of sight: 404; one they do not read for views: 403. MAX_VIEWS
    already: 409 too_many_views; a name of theirs without regard to case: 409 view_name_taken."""
    await _check_servers(db, access, body)
    # The person's row, locked until the commit, so two saves cannot pass the count together.
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    count = select(func.count()).select_from(LogView).where(LogView.owner_id == user.id)
    if await db.scalar(count) >= MAX_VIEWS:
        raise HTTPException(409, "too_many_views")
    clash = select(LogView.id).where(LogView.owner_id == user.id, func.lower(LogView.name) == body.name.lower())
    if await db.scalar(clash) is not None:
        raise HTTPException(409, "view_name_taken")
    view = LogView(
        owner_id=user.id,
        name=body.name,
        shared=body.shared,
        sources=[source.model_dump(mode="json") for source in body.sources],
        settings=body.settings.model_dump(mode="json"),
    )
    db.add(view)
    await flush_unique(db, "log_views_owner_id_name_key", "view_name_taken")
    await db.refresh(view)
    # record() last: it holds the audit chain lock until the commit.
    event = auth_event(
        request,
        actions.LOG_VIEW_CREATED,
        actor_of(user),
        mfa=True,
        target=Target(type="log_view", id=str(view.id), name=view.name),
        change=changes({}, _fields(view)),
    )
    await record(db, event)
    return _out(view, user.name, user, access)

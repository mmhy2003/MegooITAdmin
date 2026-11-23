"""The request dependencies of /api/servers: the body, read once for the guard and the handler, and the group a
request acts on, for require_group_admin and require_group_visible.

A guard dependency and a handler that both declared `body: ServerIn` would make FastAPI merge them into
{"body": {...}}; taking the body through server_in keeps it flat, and the dependency cache reads it once."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy import select

from app.access.deps import NOT_FOUND
from app.core.db import DbSession
from app.inventory.models import Server
from app.inventory.server_schemas import ServerIn, ServerPatch


async def server_in(body: ServerIn) -> ServerIn:
    """The body of POST /api/servers, read once for the guard and the handler."""
    return body


async def server_patch(body: ServerPatch) -> ServerPatch:
    """The body of PATCH /api/servers/{server_id}, read once for the guards and the handler."""
    return body


async def group_of_server(server_id: UUID, db: DbSession) -> UUID:
    """The group of the path's server. A server that does not exist answers 404."""
    group_id = await db.scalar(select(Server.server_group_id).where(Server.id == server_id))
    if group_id is None:
        raise HTTPException(404, NOT_FOUND)
    return group_id


async def group_of_new_server(body: Annotated[ServerIn, Depends(server_in)]) -> UUID:
    """The group a server is registered into."""
    return body.group_id


async def target_group_of_server(
    body: Annotated[ServerPatch, Depends(server_patch)], group_id: Annotated[UUID, Depends(group_of_server)]
) -> UUID:
    """The group the server ends up in: the body's group on a move, else its own."""
    return body.group_id if body.group_id is not None else group_id

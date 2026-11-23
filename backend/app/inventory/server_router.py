"""The routes under /api/servers and /api/server-tags: each person reads the servers of the groups they see and the
tags on them; the Owner, and an Admin in their own groups, register them."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.access.deps import CurrentAccess, require_group_admin, require_group_visible
from app.audit import audited
from app.auth.deps import CurrentUser
from app.core.db import DbSession
from app.inventory import actions, servers
from app.inventory.deps import group_of_new_server, group_of_server, server_in
from app.inventory.server_schemas import ServerIn, ServerOut

router = APIRouter()


@router.get("/servers")
async def list_servers(
    db: DbSession,
    access: CurrentAccess,
    group_id: UUID | None = None,
    tag: Annotated[list[str] | None, Query()] = None,
) -> list[ServerOut]:
    return await servers.list_servers(db, access, group_id, tag or [])


@router.get("/server-tags")
async def list_tags(db: DbSession, access: CurrentAccess) -> list[str]:
    return await servers.list_tags(db, access)


@router.get("/servers/{server_id}", dependencies=[Depends(require_group_visible(group=group_of_server))])
async def read_server(server_id: UUID, db: DbSession, access: CurrentAccess) -> ServerOut:
    return await servers.get_server(db, access, server_id)


@router.post(
    "/servers",
    dependencies=[Depends(require_group_admin(group=group_of_new_server)), audited(actions.SERVER_CREATED)],
)
async def create_server(
    body: Annotated[ServerIn, Depends(server_in)],
    request: Request,
    db: DbSession,
    user: CurrentUser,
    access: CurrentAccess,
) -> ServerOut:
    return await servers.create_server(db, request, user, access, body)

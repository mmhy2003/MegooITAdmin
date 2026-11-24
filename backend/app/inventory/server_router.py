"""The routes under /api/servers and /api/server-tags: each person reads the servers of the groups they see and the
tags on them; the Owner, and an Admin in their own groups, register, edit and remove them, and fetch and pin their SSH
host keys; anyone with Connect SSH in a server's group tests its connection. GET /api/ssh/public-key gives every
signed-in person the platform's public SSH key, and GET /api/ssh/setup-script the setup script."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.access.deps import CurrentAccess, require_grant, require_group_admin, require_group_visible
from app.access.permissions import Permission
from app.audit import audited
from app.auth.deps import CurrentUser
from app.core.db import DbSession
from app.inventory import actions, connection, servers
from app.inventory.connection_schemas import ConnectionTestResult, HostKeyFetchResult, HostKeyPin, PublicKeyOut
from app.inventory.deps import (
    group_of_new_server,
    group_of_server,
    server_in,
    server_patch,
    target_group_of_server,
)
from app.inventory.server_schemas import ServerIn, ServerOut, ServerPatch
from app.ssh import keys, setup

router = APIRouter()

admin = Depends(require_group_admin(group=group_of_server))


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


@router.patch(
    "/servers/{server_id}",
    dependencies=[
        # A move needs Admin on the group the server leaves and the one it goes to.
        Depends(require_group_admin(group=group_of_server)),
        Depends(require_group_admin(group=target_group_of_server)),
        audited(actions.SERVER_CHANGED, actions.SERVER_MOVED, actions.SERVER_TAGS_CHANGED),
    ],
)
async def update_server(
    server_id: UUID,
    body: Annotated[ServerPatch, Depends(server_patch)],
    request: Request,
    db: DbSession,
    user: CurrentUser,
    access: CurrentAccess,
) -> ServerOut:
    return await servers.update_server(db, request, user, access, server_id, body)


@router.delete(
    "/servers/{server_id}",
    status_code=204,
    dependencies=[Depends(require_group_admin(group=group_of_server)), audited(actions.SERVER_DELETED)],
)
async def delete_server(server_id: UUID, request: Request, db: DbSession, user: CurrentUser) -> Response:
    await servers.delete_server(db, request, user, server_id)
    return Response(status_code=204)


@router.post("/servers/{server_id}/host-key/fetch", dependencies=[admin, audited(actions.SERVER_HOST_KEY_FETCHED)])
async def fetch_host_key(server_id: UUID, request: Request, db: DbSession, user: CurrentUser) -> HostKeyFetchResult:
    return await connection.fetch_host_key(db, request, user, server_id)


@router.put(
    "/servers/{server_id}/host-key",
    dependencies=[admin, audited(actions.SERVER_HOST_KEY_PINNED, actions.SERVER_HOST_KEY_REPLACED)],
)
async def pin_host_key(
    server_id: UUID, body: HostKeyPin, request: Request, db: DbSession, user: CurrentUser, access: CurrentAccess
) -> ServerOut:
    return await connection.pin_host_key(db, request, user, access, server_id, body)


@router.post("/servers/{server_id}/host-key/keep", dependencies=[admin, audited(actions.SERVER_HOST_KEY_KEPT)])
async def keep_host_key(
    server_id: UUID, request: Request, db: DbSession, user: CurrentUser, access: CurrentAccess
) -> ServerOut:
    return await connection.keep_host_key(db, request, user, access, server_id)


@router.post(
    "/servers/{server_id}/connection-test",
    dependencies=[
        Depends(require_grant(Permission.CONNECT_SSH, group=group_of_server)),
        audited(actions.SERVER_CONNECTION_TESTED, actions.SERVER_HOST_KEY_MISMATCH),
    ],
)
async def test_connection(server_id: UUID, request: Request, db: DbSession, user: CurrentUser) -> ConnectionTestResult:
    return await connection.test_connection(db, request, user, server_id)


@router.get("/ssh/public-key")
async def read_public_key(user: CurrentUser) -> PublicKeyOut:
    return PublicKeyOut(public_key=keys.public_key())


@router.get("/ssh/setup-script")
async def read_setup_script(user: CurrentUser) -> Response:
    return Response(
        setup.script_text(),
        media_type="text/x-shellscript",
        headers={"Content-Disposition": 'attachment; filename="megoo-setup.sh"'},
    )

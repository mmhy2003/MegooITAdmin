"""The routes under /api/server-groups: each person lists the groups they see; the Owner creates and edits them."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.access.deps import CurrentAccess, require_owner
from app.audit import audited
from app.auth.deps import CurrentUser
from app.core.db import DbSession
from app.inventory import actions, service
from app.inventory.schemas import ServerGroupIn, ServerGroupOut, ServerGroupPatch

router = APIRouter(prefix="/server-groups")


@router.get("")
async def list_groups(db: DbSession, access: CurrentAccess) -> list[ServerGroupOut]:
    # Any signed-in person: the list filters itself by the person's access.
    return await service.list_groups(db, access)


@router.post("", dependencies=[Depends(require_owner), audited(actions.SERVER_GROUP_CREATED)])
async def create_group(body: ServerGroupIn, request: Request, db: DbSession, user: CurrentUser) -> ServerGroupOut:
    # `user` is the Owner who creates the group.
    return await service.create_group(db, request, user, body)


@router.patch("/{group_id}", dependencies=[Depends(require_owner), audited(actions.SERVER_GROUP_CHANGED)])
async def update_group(
    group_id: UUID, body: ServerGroupPatch, request: Request, db: DbSession, user: CurrentUser
) -> ServerGroupOut:
    return await service.update_group(db, request, user, group_id, body)

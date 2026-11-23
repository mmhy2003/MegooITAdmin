"""The routes under /api/users: the Owner manages the people of the platform."""

from fastapi import APIRouter, Depends, Request

from app.access.deps import require_owner
from app.audit import audited
from app.auth.deps import CurrentUser
from app.core.db import DbSession
from app.users import actions, service
from app.users.schemas import InviteIn, InviteLinkOut, UserRowOut

router = APIRouter(prefix="/users", dependencies=[Depends(require_owner)])


@router.get("")
async def list_users(db: DbSession) -> list[UserRowOut]:
    return await service.list_users(db)


@router.post("", dependencies=[audited(actions.USER_INVITED)])
async def invite(body: InviteIn, request: Request, db: DbSession, user: CurrentUser) -> InviteLinkOut:
    # `user` is the Owner who invites.
    return await service.invite(db, request, user, body)

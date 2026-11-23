"""What an Owner does with the people of the platform, between the routes and the tables."""

from collections.abc import Iterable, Mapping
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import RoleGrant
from app.access.permissions import GRANT_FIELDS
from app.audit import Event, changes, record
from app.auth import clock
from app.auth.models import User
from app.auth.service import actor_of, auth_event, lock_user, target_of
from app.inventory.models import ServerGroup
from app.users import actions
from app.users.invites import put_invite
from app.users.models import UserInvite
from app.users.schemas import GrantIn, GrantOut, InviteIn, InviteLinkOut, UserRowOut


async def grants_of(db: AsyncSession, user_ids: Iterable[UUID]) -> dict[UUID, list[GrantOut]]:
    """The group roles of these people, each one's by group name. One query."""
    query = (
        select(RoleGrant, ServerGroup.name)
        .join(ServerGroup, ServerGroup.id == RoleGrant.server_group_id)
        .where(RoleGrant.user_id.in_(list(user_ids)))
        .order_by(func.lower(ServerGroup.name))
    )
    grants: dict[UUID, list[GrantOut]] = {}
    for grant, group_name in (await db.execute(query)).all():
        grants.setdefault(grant.user_id, []).append(
            GrantOut(group_id=grant.server_group_id, group_name=group_name, **grant.fields())
        )
    return grants


def _status_of(user: User) -> str:
    if user.disabled_at is not None:
        return "disabled"
    return "invited" if user.password_hash is None else "active"


async def list_users(db: AsyncSession) -> list[UserRowOut]:
    """Every account, by name, with its status, its group roles and when its open invite expires."""
    users = (await db.scalars(select(User).order_by(func.lower(User.name), User.id))).all()
    grants = await grants_of(db, [user.id for user in users])
    invites = await db.execute(select(UserInvite.user_id, UserInvite.expires_at))
    expiries = {user_id: expires_at for user_id, expires_at in invites}
    return [
        UserRowOut(
            id=user.id,
            name=user.name,
            email=user.email,
            platform_role=user.platform_role,
            status=_status_of(user),
            mfa_enrolled=user.totp_secret is not None,
            invite_expires_at=expiries.get(user.id),
            grants=grants.get(user.id, []),
        )
        for user in users
    ]


async def _check_groups(db: AsyncSession, grants: list[GrantIn]) -> dict[UUID, ServerGroup]:
    """The groups the grants name, by ID. A group that does not exist (deleted meanwhile, say) answers 422."""
    group_ids = {g.group_id for g in grants}
    if not group_ids:
        return {}
    groups = {g.id: g for g in await db.scalars(select(ServerGroup).where(ServerGroup.id.in_(group_ids)))}
    if group_ids - groups.keys():
        raise HTTPException(422, "unknown_group")
    return groups


def _grant_event(
    request: Request,
    owner: User,
    user: User,
    action: str,
    group: ServerGroup,
    before: Mapping[str, str | bool] | None,
    after: Mapping[str, str | bool] | None,
) -> Event:
    """A grant event of the Owner's change: an absent side has every field None."""
    absent = dict.fromkeys(GRANT_FIELDS)
    return auth_event(
        request,
        action,
        actor_of(owner),
        mfa=True,
        target=target_of(user),
        context={"server_group_id": str(group.id)},
        detail={"server_group": group.name},
        change=changes(absent if before is None else before, absent if after is None else after),
    )


async def invite(db: AsyncSession, request: Request, owner: User, body: InviteIn) -> InviteLinkOut:
    """Creates the account without a password, its group roles and its invite. The token is returned only here."""
    if await db.scalar(select(User.id).where(User.email == body.email)) is not None:
        raise HTTPException(409, "email_taken")
    groups = await _check_groups(db, body.grants)
    user = User(
        email=body.email,
        name=body.name,
        password_hash=None,
        platform_role=body.platform_role,
        password_changed_at=clock.now(),
    )
    db.add(user)
    await db.flush()
    db.add_all(RoleGrant(user_id=user.id, server_group_id=g.group_id, **g.fields()) for g in body.grants)
    token, expires_at = await put_invite(db, user.id)

    await record(
        db,
        auth_event(
            request,
            actions.USER_INVITED,
            actor_of(owner),
            mfa=True,
            target=target_of(user),
            change=changes({}, {"name": user.name, "email": user.email, "platform_role": user.platform_role}),
        ),
    )
    for g in sorted(body.grants, key=lambda g: groups[g.group_id].name.lower()):
        await record(
            db, _grant_event(request, owner, user, actions.USER_GRANT_ADDED, groups[g.group_id], None, g.fields())
        )
    return InviteLinkOut(user_id=user.id, token=token, expires_at=expires_at)


async def renew_invite(db: AsyncSession, request: Request, owner: User, user_id: UUID) -> InviteLinkOut:
    """A new link in place of the old one, which stops working. Once the person has a password: 409."""
    if await db.get(User, user_id) is None:
        raise HTTPException(404, "not_found")
    user = await lock_user(db, user_id)
    if user.password_hash is not None:
        raise HTTPException(409, "already_accepted")
    token, expires_at = await put_invite(db, user.id)
    await record(
        db,
        auth_event(
            request,
            actions.USER_INVITE_RENEWED,
            actor_of(owner),
            mfa=True,
            target=target_of(user),
            detail={"expires_at": expires_at.isoformat()},
        ),
    )
    return InviteLinkOut(user_id=user.id, token=token, expires_at=expires_at)

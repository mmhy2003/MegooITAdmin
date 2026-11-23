"""What an Owner does with the people of the platform, between the routes and the tables."""

from collections.abc import Iterable, Mapping
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import RoleGrant
from app.access.deps import FORBIDDEN, deny
from app.access.permissions import GRANT_FIELDS, PlatformRole
from app.audit import Event, changes, record
from app.auth import clock
from app.auth.models import User
from app.auth.service import actor_of, auth_event, lock_user, target_of
from app.inventory.models import ServerGroup
from app.users import actions
from app.users.invites import put_invite
from app.users.models import UserInvite
from app.users.schemas import AccessIn, GrantIn, GrantOut, InviteIn, InviteLinkOut, UserRowOut


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


_enabled_owner = (User.platform_role == PlatformRole.OWNER) & User.disabled_at.is_(None)


async def _lock_for_change(db: AsyncSession, request: Request, owner: User, user_id: UUID) -> User:
    """Locks the account the Owner changes and returns it. A change to an Owner first locks every enabled Owner, in
    the order of their IDs, then checks the actor still is one: of two Owners demoting each other, the second is
    refused, so one always remains."""
    if user_id == owner.id:
        raise HTTPException(409, "own_account")
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "not_found")
    if target.platform_role == PlatformRole.OWNER:
        await db.execute(select(User.id).where(_enabled_owner).order_by(User.id).with_for_update())
        actor = await db.scalar(select(User).where(User.id == owner.id).execution_options(populate_existing=True))
        if actor.platform_role != PlatformRole.OWNER or actor.disabled_at is not None:
            await deny(request, owner, required="owner", status=403, detail=FORBIDDEN)
    return await lock_user(db, user_id)


async def _keep_an_owner(db: AsyncSession, target: User, new_role: str | None, *, disabling: bool = False) -> None:
    """Refuses a change that would leave no enabled Owner."""
    is_enabled_owner = target.platform_role == PlatformRole.OWNER and target.disabled_at is None
    if not is_enabled_owner or (new_role == PlatformRole.OWNER and not disabling):
        return
    others = await db.scalar(select(func.count()).select_from(User).where(_enabled_owner, User.id != target.id))
    if not others:
        raise HTTPException(409, "last_owner")


async def set_access(db: AsyncSession, request: Request, owner: User, user_id: UUID, body: AccessIn) -> None:
    """Sets the person's whole access in one transaction, with one event per difference. Nothing differs: 409."""
    user = await _lock_for_change(db, request, owner, user_id)
    groups = await _check_groups(db, body.grants)
    new_role = None if body.platform_role is None else body.platform_role.value
    await _keep_an_owner(db, user, new_role)

    wanted = {g.group_id: g for g in body.grants}
    query = (
        select(RoleGrant, ServerGroup)
        .join(ServerGroup, ServerGroup.id == RoleGrant.server_group_id)
        .where(RoleGrant.user_id == user.id)
    )
    stored = {grant.server_group_id: (grant, group) for grant, group in await db.execute(query)}

    # (group name, event), so the grant events are recorded by group name.
    grant_events: list[tuple[str, Event]] = []
    for group_id, (grant, group) in stored.items():
        before = grant.fields()
        if group_id not in wanted:
            await db.delete(grant)
            event = _grant_event(request, owner, user, actions.USER_GRANT_REMOVED, group, before, None)
            grant_events.append((group.name.lower(), event))
        elif (after := wanted[group_id].fields()) != before:
            for field, value in after.items():
                setattr(grant, field, value)
            grant.updated_at = clock.now()
            event = _grant_event(request, owner, user, actions.USER_GRANT_CHANGED, group, before, after)
            grant_events.append((group.name.lower(), event))
    for group_id, g in wanted.items():
        if group_id not in stored:
            db.add(RoleGrant(user_id=user.id, server_group_id=group_id, **g.fields()))
            group = groups[group_id]
            event = _grant_event(request, owner, user, actions.USER_GRANT_ADDED, group, None, g.fields())
            grant_events.append((group.name.lower(), event))

    role_event = None
    if user.platform_role != new_role:
        role_event = auth_event(
            request,
            actions.USER_ROLE_CHANGED,
            actor_of(owner),
            mfa=True,
            target=target_of(user),
            change={"platform_role": {"before": user.platform_role, "after": new_role}},
        )
        user.platform_role = new_role
    if role_event is None and not grant_events:
        raise HTTPException(409, "no_change")

    await db.flush()
    # record() last: it holds the audit chain lock until the commit.
    if role_event is not None:
        await record(db, role_event)
    for _, event in sorted(grant_events, key=lambda pair: pair[0]):
        await record(db, event)

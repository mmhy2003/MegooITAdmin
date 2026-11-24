"""The server groups each person sees, and what an Owner does with them, between the routes and the tables."""

from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import RoleGrant
from app.access.permissions import Access
from app.audit import Target, changes, record
from app.auth.models import User
from app.auth.service import actor_of, auth_event
from app.core.db import flush_refusing, flush_unique
from app.inventory import actions
from app.inventory.models import Server, ServerGroup
from app.inventory.schemas import ServerGroupIn, ServerGroupOut, ServerGroupPatch
from app.users import actions as user_actions
from app.users.service import grant_event


def _out(group: ServerGroup, member_count: int | None, server_count: int, can_manage: bool) -> ServerGroupOut:
    return ServerGroupOut(
        id=group.id,
        name=group.name,
        description=group.description,
        created_at=group.created_at,
        member_count=member_count,
        server_count=server_count,
        can_manage=can_manage,
    )


def _fields(group: ServerGroup) -> dict[str, str | None]:
    """The fields of a group its events compare."""
    return {"name": group.name, "description": group.description}


def _target(group: ServerGroup) -> Target:
    return Target(type="server_group", id=str(group.id), name=group.name)


async def _member_count(db: AsyncSession, group_id: UUID) -> int:
    return await db.scalar(select(func.count()).select_from(RoleGrant).where(RoleGrant.server_group_id == group_id))


async def _server_count(db: AsyncSession, group_id: UUID) -> int:
    return await db.scalar(select(func.count()).select_from(Server).where(Server.server_group_id == group_id))


async def list_groups(db: AsyncSession, access: Access) -> list[ServerGroupOut]:
    """The groups the person sees, by name, with how many servers each holds and whether the person manages it.
    Only an Owner is told how many people hold a role in each."""
    query = select(ServerGroup).order_by(func.lower(ServerGroup.name), ServerGroup.id)
    visible = access.visible_group_ids()
    if visible is not None:
        query = query.where(ServerGroup.id.in_(visible))
    groups = (await db.scalars(query)).all()
    servers = dict(
        (await db.execute(select(Server.server_group_id, func.count()).group_by(Server.server_group_id))).all()
    )
    members: dict[UUID, int] | None = None
    if access.is_owner:
        counted = select(RoleGrant.server_group_id, func.count()).group_by(RoleGrant.server_group_id)
        members = dict((await db.execute(counted)).all())
    return [
        _out(
            group,
            None if members is None else members.get(group.id, 0),
            servers.get(group.id, 0),
            access.manages(group.id),
        )
        for group in groups
    ]


async def _check_name(db: AsyncSession, name: str, group_id: UUID | None = None) -> None:
    """Another group with the name, without regard to case: 409."""
    query = select(ServerGroup.id).where(func.lower(ServerGroup.name) == name.lower())
    if group_id is not None:
        query = query.where(ServerGroup.id != group_id)
    if await db.scalar(query) is not None:
        raise HTTPException(409, "name_taken")


async def create_group(db: AsyncSession, request: Request, owner: User, body: ServerGroupIn) -> ServerGroupOut:
    await _check_name(db, body.name)
    group = ServerGroup(name=body.name, description=body.description)
    db.add(group)
    await flush_unique(db, "server_groups_name_key", "name_taken")
    await db.refresh(group)
    # record() last: it holds the audit chain lock until the commit.
    await record(
        db,
        auth_event(
            request,
            actions.SERVER_GROUP_CREATED,
            actor_of(owner),
            mfa=True,
            target=_target(group),
            change=changes({}, _fields(group)),
        ),
    )
    return _out(group, 0, 0, True)


async def update_group(
    db: AsyncSession, request: Request, owner: User, group_id: UUID, body: ServerGroupPatch
) -> ServerGroupOut:
    """Changes the fields sent. Nothing differs: 409."""
    group = await db.scalar(select(ServerGroup).where(ServerGroup.id == group_id).with_for_update())
    if group is None:
        raise HTTPException(404, "not_found")
    before = _fields(group)
    after = before | {field: getattr(body, field) for field in body.model_fields_set}
    if after["name"] is None:
        after["name"] = before["name"]
    change = changes(before, after)
    if change is None:
        raise HTTPException(409, "no_change")
    if after["name"] != before["name"]:
        await _check_name(db, after["name"], group.id)
    group.name, group.description = after["name"], after["description"]
    await flush_unique(db, "server_groups_name_key", "name_taken")
    await record(
        db,
        auth_event(
            request,
            actions.SERVER_GROUP_CHANGED,
            actor_of(owner),
            mfa=True,
            # The group as it is named now; the change holds the old name.
            target=_target(group),
            change=change,
        ),
    )
    return _out(group, await _member_count(db, group.id), await _server_count(db, group.id), True)


async def delete_group(db: AsyncSession, request: Request, owner: User, group_id: UUID) -> None:
    """Deletes the group and the roles in it: one grant_removed per person, by name, then the deletion.
    A group that holds a server: 409."""
    group = await db.scalar(select(ServerGroup).where(ServerGroup.id == group_id).with_for_update())
    if group is None:
        raise HTTPException(404, "not_found")
    if await _server_count(db, group.id) > 0:
        raise HTTPException(409, "group_has_servers")
    query = (
        select(RoleGrant, User)
        .join(User, User.id == RoleGrant.user_id)
        .where(RoleGrant.server_group_id == group.id)
        .order_by(func.lower(User.name), User.id)
    )
    grants = (await db.execute(query)).all()
    events = [
        grant_event(request, owner, user, user_actions.USER_GRANT_REMOVED, group, grant.fields(), None)
        for grant, user in grants
    ]
    deleted = auth_event(
        request,
        actions.SERVER_GROUP_DELETED,
        actor_of(owner),
        mfa=True,
        target=_target(group),
        change=changes(_fields(group), {}),
    )
    for grant, _ in grants:
        await db.delete(grant)
    await db.delete(group)
    # A server registered into the group meanwhile: only the foreign key sees it.
    await flush_refusing(db, {"servers_server_group_id_fkey": (409, "group_has_servers")})
    for event in [*events, deleted]:
        await record(db, event)

"""The servers each person sees, and what an Admin does with them in their groups, between the routes and the
tables."""

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.permissions import Access, Permission
from app.audit import Event, Target, changes, record
from app.auth.models import User
from app.auth.service import actor_of, auth_event
from app.core.db import flush_refusing
from app.inventory import actions
from app.inventory.models import Server, ServerGroup, ServerTag
from app.inventory.server_schemas import HostKeyOffer, HostKeyState, ServerIn, ServerOut, ServerPatch
from app.ssh import hostkeys

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


def host_key_state(server: Server) -> HostKeyState:
    if server.os != "linux":
        return "none"
    if server.host_key is None:
        return "not_pinned"
    return "changed" if server.host_key_changed_at is not None else "pinned"


def _out(server: Server, group_name: str, tags: list[str], access: Access) -> ServerOut:
    state = host_key_state(server)
    offered = None
    if state == "changed" and server.host_key_offered is not None:
        offered = HostKeyOffer(
            fingerprint=hostkeys.fingerprint(server.host_key_offered),
            type=hostkeys.key_type(server.host_key_offered),
            at=server.host_key_offered_at,
        )
    pinned = server.host_key is not None
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
        host_key_state=state,
        host_key_fingerprint=hostkeys.fingerprint(server.host_key) if pinned else None,
        host_key_type=hostkeys.key_type(server.host_key) if pinned else None,
        host_key_pinned_at=server.host_key_pinned_at,
        host_key_changed_at=server.host_key_changed_at,
        host_key_offered=offered,
        created_at=server.created_at,
        updated_at=server.updated_at,
        can_manage=access.manages(server.server_group_id),
        can_connect=server.os == "linux" and access.allows(Permission.CONNECT_SSH, server.server_group_id),
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


async def list_servers(db: AsyncSession, access: Access, group_id: UUID | None, tags: list[str]) -> list[ServerOut]:
    """The servers the person sees, by name, in one group when asked, carrying every tag asked for."""
    query = select(Server, ServerGroup.name).join(ServerGroup, ServerGroup.id == Server.server_group_id)
    visible = access.visible_group_ids()
    if visible is not None:
        query = query.where(Server.server_group_id.in_(visible))
    if group_id is not None:
        query = query.where(Server.server_group_id == group_id)
    for tag in {tag.strip().lower() for tag in tags}:
        query = query.where(Server.id.in_(select(ServerTag.server_id).where(ServerTag.tag == tag)))
    rows = (await db.execute(query.order_by(func.lower(Server.name), Server.id))).all()
    tags_of = await _tags_of(db, [server.id for server, _ in rows])
    return [_out(server, group_name, tags_of.get(server.id, []), access) for server, group_name in rows]


async def list_tags(db: AsyncSession, access: Access) -> list[str]:
    """The tags in use on the servers the person sees, sorted."""
    query = select(ServerTag.tag).distinct().join(Server, Server.id == ServerTag.server_id)
    visible = access.visible_group_ids()
    if visible is not None:
        query = query.where(Server.server_group_id.in_(visible))
    return list((await db.scalars(query.order_by(ServerTag.tag))).all())


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


async def update_server(
    db: AsyncSession, request: Request, user: User, access: Access, server_id: UUID, body: ServerPatch
) -> ServerOut:
    """Changes the fields sent, moves the server to the group sent and sets its tags: one event for each that
    differs, in that order. Nothing differs: 409."""
    server = await db.scalar(select(Server).where(Server.id == server_id).with_for_update())
    if server is None:
        raise HTTPException(404, "not_found")
    group = await _group(db, server.server_group_id)
    tags = (await _tags_of(db, [server.id])).get(server.id, [])

    before = _fields(server)
    sent = body.model_dump(include=set(FIELDS) & body.model_fields_set)
    after = before | sent
    target = group
    if body.group_id is not None and body.group_id != group.id:
        target = await _group(db, body.group_id)
    new_tags = tags if body.tags is None else body.tags

    changed = changes(before, after)
    moved = {"group": {"before": group.name, "after": target.name}} if target is not group else None
    tags_changed = {"tags": {"before": tags, "after": new_tags}} if new_tags != tags else None
    if changed is None and moved is None and tags_changed is None:
        raise HTTPException(409, "no_change")
    if after["name"] != before["name"]:
        await _check_name(db, after["name"], server.id)

    # An unconfirmed candidate belongs to the old address; a pinned key is never touched by an edit.
    moved_address = (after["address"], after["port"]) != (before["address"], before["port"])
    if moved_address and server.host_key is None:
        server.host_key_offered = server.host_key_offered_at = None
    for field, value in after.items():
        setattr(server, field, value)
    server.server_group_id = target.id
    server.updated_at = func.now()
    removed = set(tags) - set(new_tags)
    if removed:
        await db.execute(delete(ServerTag).where(ServerTag.server_id == server.id, ServerTag.tag.in_(removed)))
    db.add_all(ServerTag(server_id=server.id, tag=tag) for tag in set(new_tags) - set(tags))
    await flush_refusing(db, REFUSALS)
    await db.refresh(server)

    # record() last: it holds the audit chain lock until the commit.
    if changed is not None:
        await record(db, _event(request, user, actions.SERVER_CHANGED, server, change=changed))
    if moved is not None:
        detail = {"from_group_id": str(group.id), "to_group_id": str(target.id)}
        await record(db, _event(request, user, actions.SERVER_MOVED, server, change=moved, detail=detail))
    if tags_changed is not None:
        await record(db, _event(request, user, actions.SERVER_TAGS_CHANGED, server, change=tags_changed))
    return _out(server, target.name, new_tags, access)


async def delete_server(db: AsyncSession, request: Request, user: User, server_id: UUID) -> None:
    """Deletes the server; its tags go with it in the database. The event keeps every field it had and the
    fingerprint of its pinned host key."""
    server = await db.scalar(select(Server).where(Server.id == server_id).with_for_update())
    if server is None:
        raise HTTPException(404, "not_found")
    group = await _group(db, server.server_group_id)
    tags = (await _tags_of(db, [server.id])).get(server.id, [])
    fingerprint = hostkeys.fingerprint(server.host_key) if server.host_key is not None else None
    change = changes(_fields(server) | {"group": group.name, "tags": tags, "host_key_fingerprint": fingerprint}, {})
    event = _event(request, user, actions.SERVER_DELETED, server, change=change)
    await db.delete(server)
    await db.flush()
    # record() last: it holds the audit chain lock until the commit.
    await record(db, event)

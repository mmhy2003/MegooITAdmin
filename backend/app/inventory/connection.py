"""What the Owner and the Admins of a group do with a server's SSH host key, between the routes, the SSH client and
the tables. The backend pins only a key it fetched itself, and never holds a row lock while it talks to a server."""

from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.permissions import Access
from app.audit import Actor, Event, Result, Source, record, source_of
from app.auth.models import User
from app.auth.service import actor_of
from app.inventory import actions, servers
from app.inventory.connection_schemas import HostKeyFetchResult, HostKeyPin
from app.inventory.models import Server
from app.inventory.server_schemas import ServerOut
from app.ssh import client, hostkeys


class ConnectionRefused(Exception):
    """Refused before connecting: detail is not_an_ssh_server, host_key_not_pinned or host_key_changed."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _event(
    server: Server,
    action: str,
    *,
    actor: Actor,
    source: Source | None,
    result: Result = Result.SUCCESS,
    change: dict | None = None,
    detail: dict | None = None,
    reason: str | None = None,
) -> Event:
    """An event of the server, in the context of its group."""
    return Event(
        action=action,
        actor=actor,
        result=result,
        target=servers._target(server),
        change=change,
        result_detail=detail,
        reason=reason,
        context={"server_group_id": str(server.server_group_id)},
        source=source,
    )


def _who(request: Request, user: User) -> tuple[Actor, Source]:
    return actor_of(user), source_of(request, auth_method="password", mfa=True)


async def _load(db: AsyncSession, server_id: UUID, *, lock: bool = False) -> Server:
    """The server, read again from the database; with `lock`, locked until the commit."""
    query = select(Server).where(Server.id == server_id).execution_options(populate_existing=True)
    server = await db.scalar(query.with_for_update() if lock else query)
    if server is None:
        raise HTTPException(404, "not_found")
    return server


def _ssh_server(server: Server) -> None:
    if server.os != "linux":
        raise HTTPException(409, "not_an_ssh_server")


async def fetch_host_key(db: AsyncSession, request: Request, user: User, server_id: UUID) -> HostKeyFetchResult:
    """Reads the server's key without signing in and keeps it as the candidate a pin may confirm. A failed fetch
    answers 200 with its reason: the attempt is recorded too."""
    server = await _load(db, server_id)
    _ssh_server(server)
    if server.host_key is not None:
        raise HTTPException(409, "host_key_pinned")
    actor, source = _who(request, user)
    address = {"address": server.address, "port": server.port}
    try:
        line = await client.fetch_host_key(server.address, server.port)
    except client.SshFailure as failure:
        event = _event(
            server,
            actions.SERVER_HOST_KEY_FETCHED,
            actor=actor,
            source=source,
            result=Result.FAILURE,
            detail={"reason": failure.reason} | address,
        )
        # record() last: it holds the audit chain lock until the commit.
        await record(db, event)
        return HostKeyFetchResult(ok=False, reason=failure.reason, fingerprint=None, type=None)

    # Someone may have pinned a key while this request talked to the server.
    server = await _load(db, server_id, lock=True)
    if server.host_key is not None:
        raise HTTPException(409, "host_key_pinned")
    server.host_key_offered = line
    server.host_key_offered_at = func.now()
    await db.flush()
    fingerprint, key_type = hostkeys.fingerprint(line), hostkeys.key_type(line)
    detail = {"fingerprint": fingerprint, "type": key_type} | address
    # record() last: it holds the audit chain lock until the commit.
    await record(db, _event(server, actions.SERVER_HOST_KEY_FETCHED, actor=actor, source=source, detail=detail))
    return HostKeyFetchResult(ok=True, reason=None, fingerprint=fingerprint, type=key_type)


async def pin_host_key(
    db: AsyncSession, request: Request, user: User, access: Access, server_id: UUID, body: HostKeyPin
) -> ServerOut:
    """Pins the candidate the backend fetched, when it is the key whose fingerprint the admin compared."""
    server = await _load(db, server_id, lock=True)
    _ssh_server(server)
    if server.host_key is not None:
        raise HTTPException(409, "host_key_pinned")
    offered = server.host_key_offered
    if offered is None or hostkeys.fingerprint(offered) != body.fingerprint:
        raise HTTPException(409, "stale_host_key")
    server.host_key = offered
    server.host_key_pinned_at = func.now()
    server.host_key_offered = server.host_key_offered_at = server.host_key_changed_at = None
    await db.flush()
    await db.refresh(server)

    actor, source = _who(request, user)
    change = {"host_key_fingerprint": {"before": None, "after": body.fingerprint}}
    event = _event(
        server,
        actions.SERVER_HOST_KEY_PINNED,
        actor=actor,
        source=source,
        change=change,
        detail={"type": hostkeys.key_type(offered)},
    )
    # record() last: it holds the audit chain lock until the commit.
    await record(db, event)
    return await servers.get_server(db, access, server_id)

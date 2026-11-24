"""What the Owner and the Admins of a group do with a server's SSH host key, and the connection test of anyone with
Connect SSH, between the routes, the SSH client and the tables. The backend pins only a key it fetched itself, and
never holds a row lock while it talks to a server. open_connection() is the only door to a server."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import get_args
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.permissions import Access
from app.audit import Actor, Event, Result, Source, record, source_of
from app.auth.models import User
from app.auth.service import actor_of
from app.core.db import SessionLocal
from app.inventory import actions, servers
from app.inventory.connection_schemas import (
    Check,
    CheckName,
    CheckStatus,
    ConnectionTestResult,
    HostKeyFetchResult,
    HostKeyPin,
)
from app.inventory.models import Server
from app.inventory.server_schemas import ServerOut
from app.ssh import client, hostkeys
from app.ssh.setup import ctl_version


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
    """Pins the candidate the backend fetched, when it is the key whose fingerprint the admin compared. On a server
    flagged for a changed key, it accepts the key the server presented, with the admin's reason, and unblocks it."""
    server = await _load(db, server_id, lock=True)
    _ssh_server(server)
    before = server.host_key
    changed = server.host_key_changed_at is not None
    if before is not None and not changed:
        raise HTTPException(409, "host_key_pinned")
    if changed and body.reason is None:
        raise HTTPException(422, "reason_required")
    offered = server.host_key_offered
    if offered is None or hostkeys.fingerprint(offered) != body.fingerprint:
        raise HTTPException(409, "stale_host_key")
    server.host_key = offered
    server.host_key_pinned_at = func.now()
    server.host_key_offered = server.host_key_offered_at = server.host_key_changed_at = None
    await db.flush()
    await db.refresh(server)

    actor, source = _who(request, user)
    detail = {"type": hostkeys.key_type(offered)}
    if before is None:
        change = {"host_key_fingerprint": {"before": None, "after": body.fingerprint}}
        event = _event(
            server, actions.SERVER_HOST_KEY_PINNED, actor=actor, source=source, change=change, detail=detail
        )
    else:
        change = {"host_key_fingerprint": {"before": hostkeys.fingerprint(before), "after": body.fingerprint}}
        event = _event(
            server,
            actions.SERVER_HOST_KEY_REPLACED,
            actor=actor,
            source=source,
            change=change,
            detail=detail,
            reason=body.reason,
        )
    # record() last: it holds the audit chain lock until the commit.
    await record(db, event)
    return await servers.get_server(db, access, server_id)


async def keep_host_key(db: AsyncSession, request: Request, user: User, access: Access, server_id: UUID) -> ServerOut:
    """Turns down the key a flagged server presented: removes the block and the candidate, keeps the pinned key. A
    server that still presents the other key is flagged again by its next connection."""
    server = await _load(db, server_id, lock=True)
    _ssh_server(server)
    if server.host_key_changed_at is None:
        raise HTTPException(409, "host_key_not_changed")
    presented = server.host_key_offered
    server.host_key_offered = server.host_key_offered_at = server.host_key_changed_at = None
    await db.flush()

    actor, source = _who(request, user)
    detail = {
        "pinned_fingerprint": hostkeys.fingerprint(server.host_key),
        "presented_fingerprint": None if presented is None else hostkeys.fingerprint(presented),
    }
    # record() last: it holds the audit chain lock until the commit.
    await record(db, _event(server, actions.SERVER_HOST_KEY_KEPT, actor=actor, source=source, detail=detail))
    return await servers.get_server(db, access, server_id)


async def _flag_changed(server: Server, presented: str | None, *, actor: Actor, source: Source | None) -> None:
    """Blocks the server and records server.host_key_mismatch in a transaction of its own, so a caller's rollback
    keeps both. `presented` is the key the server presented, or None when it could not be read."""
    async with SessionLocal() as session:
        row = await _load(session, server.id, lock=True)
        row.host_key_changed_at = func.now()
        row.host_key_offered = presented
        row.host_key_offered_at = func.now() if presented is not None else None
        await session.flush()
        detail = {
            "pinned_fingerprint": hostkeys.fingerprint(row.host_key),
            "presented_fingerprint": None if presented is None else hostkeys.fingerprint(presented),
            "address": row.address,
            "port": row.port,
        }
        event = _event(
            row, actions.SERVER_HOST_KEY_MISMATCH, actor=actor, source=source, result=Result.FAILURE, detail=detail
        )
        # record() last: it holds the audit chain lock until the commit.
        await record(session, event)
        await session.commit()


@asynccontextmanager
async def open_connection(
    server: Server, *, actor: Actor, source: Source | None
) -> AsyncIterator[client.Connection]:
    """The door to a server for every feature: signs in with the platform's key, only with the pinned host key.
    Refuses a non-Linux server, one without a pinned key and one that is flagged (ConnectionRefused). When the
    server presents another key, it flags the server and re-raises client.HostKeyChanged."""
    if server.os != "linux":
        raise ConnectionRefused("not_an_ssh_server")
    if server.host_key is None:
        raise ConnectionRefused("host_key_not_pinned")
    if server.host_key_changed_at is not None:
        raise ConnectionRefused("host_key_changed")
    username = server.connection_settings["username"]
    try:
        async with client.connect(server.address, server.port, username, server.host_key) as conn:
            yield conn
    except client.HostKeyChanged as changed:
        await _flag_changed(server, changed.presented, actor=actor, source=source)
        raise


# The host_key and platform_key checks of a failure before the account check; any other outcome passed both.
_SIGN_IN_CHECKS: dict[str, tuple[CheckStatus, CheckStatus]] = {
    "unreachable": ("not_run", "not_run"),
    "ssh_error": ("not_run", "not_run"),
    "host_key_changed": ("failed", "not_run"),
    "key_refused": ("passed", "failed"),
}


LOG_GROUPS = frozenset({"systemd-journal", "adm"})


def _passed(ok: bool) -> CheckStatus:
    return "passed" if ok else "failed"


def _checks(reason: str | None, account: tuple[int, list[str]] | None, sudo: client.Setup | None) -> list[Check]:
    """The seven checks of an outcome, in CheckName order. `account` and `sudo` are what was read, or None."""
    statuses: tuple[CheckStatus, ...] = _SIGN_IN_CHECKS.get(reason, ("passed", "passed"))
    if account is None:
        statuses += ("not_run",) * 3
    else:
        uid, groups = account
        statuses += (_passed(uid != 0), _passed("docker" not in groups), _passed(LOG_GROUPS <= set(groups)))
    if sudo is None:
        statuses += ("not_run",) * 2
    else:
        statuses += (
            _passed(sudo.version is not None and sudo.version >= ctl_version()),
            "not_run" if sudo.limited is None else _passed(sudo.limited),
        )
    return [Check(name=name, status=status) for name, status in zip(get_args(CheckName), statuses, strict=True)]


def _reason(account: tuple[int, list[str]], sudo: client.Setup, bundled: int) -> str | None:
    """The first failed check, in the order root, docker, log groups, checker, too wide; an unreadable sudo list with
    a working checker is account_check_failed."""
    uid, groups = account
    if uid == 0:
        return "account_is_root"
    if "docker" in groups:
        return "account_in_docker_group"
    if not LOG_GROUPS <= set(groups):
        return "account_not_in_log_groups"
    if sudo.version is None or sudo.version < bundled:
        return "sudo_checker_missing"
    if sudo.limited is False:
        return "sudo_too_wide"
    if sudo.limited is None:
        return "account_check_failed"
    return None


async def test_connection(db: AsyncSession, request: Request, user: User, server_id: UUID) -> ConnectionTestResult:
    """Signs in as the server's account and runs the seven checks: the host key, the platform key, not root, not in
    the docker group, in the log groups, megoo-ctl answering through sudo, and sudo allowing only megoo-ctl. A failed
    test answers 200 with its reason; a server that cannot be tried (not Linux, not pinned, flagged) answers 409."""
    server = await _load(db, server_id)
    actor, source = _who(request, user)
    username = server.connection_settings["username"]
    account: tuple[int, list[str]] | None = None
    sudo: client.Setup | None = None
    try:
        async with open_connection(server, actor=actor, source=source) as conn:
            account = await client.account_of(conn)
            sudo = await client.setup_of(conn)
    except ConnectionRefused as refused:
        raise HTTPException(409, refused.detail) from refused
    except client.SshFailure as failure:
        reason: str | None = failure.reason
    else:
        reason = _reason(account, sudo, ctl_version())

    checks = _checks(reason, account, sudo)
    detail = {
        "username": username,
        "address": server.address,
        "port": server.port,
        "reason": reason,
        "checks": {check.name: check.status for check in checks},
    }
    result = Result.SUCCESS if reason is None else Result.FAILURE
    event = _event(
        server, actions.SERVER_CONNECTION_TESTED, actor=actor, source=source, result=result, detail=detail
    )
    # record() last: it holds the audit chain lock until the commit.
    await record(db, event)
    return ConnectionTestResult(ok=reason is None, reason=reason, checks=checks)

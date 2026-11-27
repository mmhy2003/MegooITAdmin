"""The log files a group's members may follow: the rules of a pattern, how a path matches one, and how an Admin
lists, adds and removes a group's patterns.

A pattern is an absolute path whose segments may hold "*" (any characters) and "?" (one character). A wildcard
never crosses a "/", and the first segment holds none, so no pattern can reach every directory of the server.
"""

import re
from collections.abc import Iterable
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.permissions import Access
from app.audit import Event, Target, record
from app.auth.models import User
from app.auth.service import actor_of, auth_event
from app.core.db import flush_unique
from app.inventory.models import ServerGroup
from app.logs import actions
from app.logs.models import LogFileAllowlist
from app.logs.sources import PATH_CHARS, check_path

if TYPE_CHECKING:  # the schemas import check_pattern from here
    from app.logs.schemas import AllowlistOut, PatternIn, PatternOut

MAX_PATTERNS = 50
STARTER_PATTERNS = ("/var/log/syslog", "/var/log/messages", "/var/log/nginx/*.log", "/var/log/apache2/*.log")
PATTERN = re.compile(rf"/[*?{PATH_CHARS}]{{0,254}}")  # wildcards first: PATH_CHARS ends with "-"
WILDCARDS = {"*": "[^/]*", "?": "[^/]"}


def check_pattern(value: str) -> str:
    """ValueError unless PATTERN matches, every segment is non-empty and not "." or "..", and the first segment
    holds no wildcard ("/*", "/v*r/log" are refused)."""
    if not PATTERN.fullmatch(value):
        raise ValueError("not a pattern")
    check_path(value.replace("*", "x").replace("?", "x"))  # the segment rule of a path, wildcards as plain letters
    if any(wildcard in value[1:].split("/")[0] for wildcard in WILDCARDS):
        raise ValueError("a wildcard in the first segment")
    return value


def _regex(pattern: str) -> re.Pattern[str]:
    return re.compile("".join(WILDCARDS.get(char) or re.escape(char) for char in pattern))


def matches(path: str, patterns: Iterable[str]) -> bool:
    """Whether the path matches one pattern. "*" is "[^/]*" and "?" is "[^/]"; every other character is itself
    (re.escape). The whole path must match."""
    return any(_regex(pattern).fullmatch(path) for pattern in patterns)


async def patterns_of(db: AsyncSession, group_ids: Iterable[UUID]) -> dict[UUID, list[str]]:
    """The patterns of each asked group, sorted; a group without any is absent."""
    query = (
        select(LogFileAllowlist.server_group_id, LogFileAllowlist.pattern)
        .where(LogFileAllowlist.server_group_id.in_(list(group_ids)))
        .order_by(LogFileAllowlist.pattern)
    )
    patterns: dict[UUID, list[str]] = {}
    for group_id, pattern in await db.execute(query):
        patterns.setdefault(group_id, []).append(pattern)
    return patterns


def starter_rows(group_id: UUID) -> list[LogFileAllowlist]:
    """The rows of the starter patterns of a new group."""
    return [LogFileAllowlist(server_group_id=group_id, pattern=pattern) for pattern in STARTER_PATTERNS]


def _out(row: LogFileAllowlist) -> "PatternOut":
    from app.logs.schemas import PatternOut

    return PatternOut(id=row.id, pattern=row.pattern, created_at=row.created_at)


async def _lock_group(db: AsyncSession, group_id: UUID) -> ServerGroup:
    """The group, locked until the commit, so two Admins cannot pass the count together. None: 404."""
    group = await db.scalar(select(ServerGroup).where(ServerGroup.id == group_id).with_for_update())
    if group is None:
        raise HTTPException(404, "not_found")
    return group


def _event(
    request: Request,
    action: str,
    user: User,
    group: ServerGroup,
    before: str | None,
    after: str | None,
    pattern_id: UUID,
) -> Event:
    return auth_event(
        request,
        action,
        actor_of(user),
        mfa=True,
        target=Target(type="server_group", id=str(group.id), name=group.name),
        change={"pattern": {"before": before, "after": after}},
        detail={"pattern_id": str(pattern_id)},
    )


async def list_patterns(db: AsyncSession, access: Access, group_id: UUID) -> "AllowlistOut":
    """The group's patterns, by pattern, and whether the person manages them. No such group: 404."""
    from app.logs.schemas import AllowlistOut

    if await db.scalar(select(ServerGroup.id).where(ServerGroup.id == group_id)) is None:
        raise HTTPException(404, "not_found")
    query = select(LogFileAllowlist).where(LogFileAllowlist.server_group_id == group_id)
    rows = await db.scalars(query.order_by(LogFileAllowlist.pattern))
    return AllowlistOut(can_manage=access.manages(group_id), patterns=[_out(row) for row in rows])


async def add_pattern(
    db: AsyncSession, request: Request, user: User, group_id: UUID, body: "PatternIn"
) -> "PatternOut":
    """Adds a pattern to the group. MAX_PATTERNS already: 409 too_many_patterns; the same one: 409 pattern_exists."""
    group = await _lock_group(db, group_id)
    count = select(func.count()).select_from(LogFileAllowlist).where(LogFileAllowlist.server_group_id == group.id)
    if await db.scalar(count) >= MAX_PATTERNS:
        raise HTTPException(409, "too_many_patterns")
    row = LogFileAllowlist(server_group_id=group.id, pattern=body.pattern)
    db.add(row)
    await flush_unique(db, "log_file_allowlist_server_group_id_pattern_key", "pattern_exists")
    await db.refresh(row)
    # record() last: it holds the audit chain lock until the commit.
    await record(db, _event(request, actions.LOG_ALLOWLIST_PATTERN_ADDED, user, group, None, row.pattern, row.id))
    return _out(row)


async def remove_pattern(db: AsyncSession, request: Request, user: User, group_id: UUID, pattern_id: UUID) -> None:
    """Removes one of the group's patterns. None of that ID in this group: 404."""
    group = await _lock_group(db, group_id)
    row = await db.scalar(
        select(LogFileAllowlist).where(LogFileAllowlist.id == pattern_id, LogFileAllowlist.server_group_id == group.id)
    )
    if row is None:
        raise HTTPException(404, "not_found")
    await db.delete(row)
    await db.flush()
    await record(db, _event(request, actions.LOG_ALLOWLIST_PATTERN_REMOVED, user, group, row.pattern, None, row.id))

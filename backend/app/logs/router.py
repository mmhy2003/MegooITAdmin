"""The routes under /api/server-groups/{group_id}/log-allowlist: the group's members list the log file patterns; the
Owner and the group's Admins add and remove them."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.access.deps import CurrentAccess, require_group_admin, require_group_visible
from app.audit import audited
from app.auth.deps import CurrentUser
from app.core.db import DbSession
from app.logs import actions, allowlist
from app.logs.schemas import AllowlistOut, PatternIn, PatternOut

router = APIRouter(prefix="/server-groups/{group_id}/log-allowlist")


@router.get("", dependencies=[Depends(require_group_visible())])
async def list_patterns(group_id: UUID, db: DbSession, access: CurrentAccess) -> AllowlistOut:
    return await allowlist.list_patterns(db, access, group_id)


@router.post("", dependencies=[Depends(require_group_admin()), audited(actions.LOG_ALLOWLIST_PATTERN_ADDED)])
async def add_pattern(
    group_id: UUID, body: PatternIn, request: Request, db: DbSession, user: CurrentUser
) -> PatternOut:
    return await allowlist.add_pattern(db, request, user, group_id, body)


@router.delete(
    "/{pattern_id}",
    status_code=204,
    dependencies=[Depends(require_group_admin()), audited(actions.LOG_ALLOWLIST_PATTERN_REMOVED)],
)
async def remove_pattern(
    group_id: UUID, pattern_id: UUID, request: Request, db: DbSession, user: CurrentUser
) -> Response:
    await allowlist.remove_pattern(db, request, user, group_id, pattern_id)
    return Response(status_code=204)

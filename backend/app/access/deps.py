"""The route dependencies that say who may call a route: require_owner, require_grant, require_group_visible and
require_group_admin.

Each refusal is recorded as access.denied in a transaction of its own, then raised, so the request's rollback
keeps the event. Each guard carries an `access_requirement` attribute, read by tests/security/routes.py."""

from collections.abc import Awaitable, Callable
from types import MappingProxyType
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.routing import iter_route_contexts
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.actions import ACCESS_DENIED
from app.access.models import RoleGrant
from app.access.permissions import Access, GroupGrant, GroupRole, Permission, PlatformRole
from app.audit import Event, Result, Target, record_alone, source_of
from app.auth.deps import CurrentUser
from app.auth.models import User
from app.auth.service import actor_of
from app.core.db import DbSession

FORBIDDEN = "forbidden"
NOT_FOUND = "not_found"


async def load_access(db: AsyncSession, user: User) -> Access:
    """One query for the person's group roles (none for an Owner or an Auditor)."""
    groups: dict[UUID, GroupGrant] = {}
    if user.platform_role is None:
        for grant in await db.scalars(select(RoleGrant).where(RoleGrant.user_id == user.id)):
            permissions = frozenset(p for p in Permission if getattr(grant, p.value))
            groups[grant.server_group_id] = GroupGrant(role=GroupRole(grant.role), permissions=permissions)
    platform_role = None if user.platform_role is None else PlatformRole(user.platform_role)
    return Access(user_id=user.id, platform_role=platform_role, groups=MappingProxyType(groups))


async def current_access(db: DbSession, user: CurrentUser) -> Access:
    return await load_access(db, user)


CurrentAccess = Annotated[Access, Depends(current_access)]


def route_of(request: Request) -> str:
    """'POST /api/users': the method and the route's path template, never the address with IDs filled in.

    Since FastAPI 0.165 scope["route"] holds the route as declared in its router, without the prefixes of the
    routers it was included through, so the full template comes from the app's route contexts."""
    route = request.scope["route"]
    path = next(
        (context.path for context in iter_route_contexts(request.app.routes) if context.original_route is route),
        route.path_format,
    )
    return f"{request.method} {path}"


async def deny(
    request: Request, user: User, *, required: str, status: int, detail: str, group_id: UUID | None = None
) -> NoReturn:
    """Records access.denied with record_alone, so the request's rollback keeps it, then raises HTTPException.
    AuditChainBusy is not caught: a refusal without its event answers 500."""
    await record_alone(
        Event(
            action=ACCESS_DENIED,
            actor=actor_of(user),
            result=Result.FAILURE,
            target=Target(type="server_group", id=str(group_id)) if group_id is not None else None,
            result_detail={"required": required, "route": route_of(request)},
            source=source_of(request, auth_method="password", mfa=True),
        )
    )
    raise HTTPException(status, detail)


async def require_owner(request: Request, user: CurrentUser, access: CurrentAccess) -> Access:
    if not access.is_owner:
        await deny(request, user, required="owner", status=403, detail=FORBIDDEN)
    return access


require_owner.access_requirement = "owner"


async def group_from_path(group_id: UUID) -> UUID:
    return group_id


GroupOf = Callable[..., Awaitable[UUID]]


def require_grant(permission: Permission, *, group: GroupOf = group_from_path):
    """A dependency: the person must see the request's group (else 404) and hold `permission` in it (else 403).
    `group` is a dependency that returns the group of the request's target; by default the path's group_id."""

    async def grant_guard(
        request: Request, user: CurrentUser, access: CurrentAccess, group_id: Annotated[UUID, Depends(group)]
    ) -> Access:
        if not access.sees(group_id):
            await deny(request, user, required=permission.value, status=404, detail=NOT_FOUND, group_id=group_id)
        if not access.allows(permission, group_id):
            await deny(request, user, required=permission.value, status=403, detail=FORBIDDEN, group_id=group_id)
        return access

    grant_guard.access_requirement = permission.value
    return grant_guard


def require_group_visible(*, group: GroupOf = group_from_path):
    """A dependency: the person must see the request's group, else 404."""

    async def group_guard(
        request: Request, user: CurrentUser, access: CurrentAccess, group_id: Annotated[UUID, Depends(group)]
    ) -> Access:
        if not access.sees(group_id):
            await deny(request, user, required="group", status=404, detail=NOT_FOUND, group_id=group_id)
        return access

    group_guard.access_requirement = "group"
    return group_guard


def require_group_admin(*, group: GroupOf = group_from_path):
    """A dependency: the person must see the request's group (else 404) and manage it (else 403)."""

    async def admin_guard(
        request: Request, user: CurrentUser, access: CurrentAccess, group_id: Annotated[UUID, Depends(group)]
    ) -> Access:
        if not access.sees(group_id):
            await deny(request, user, required="admin", status=404, detail=NOT_FOUND, group_id=group_id)
        if not access.manages(group_id):
            await deny(request, user, required="admin", status=403, detail=FORBIDDEN, group_id=group_id)
        return access

    admin_guard.access_requirement = "admin"
    return admin_guard

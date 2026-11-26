"""The routes under /api/servers/{id}/checks and /containers: everyone who sees a server reads its checks and its
containers; the data of the top processes check needs View processes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.access.deps import CurrentAccess, require_group_visible
from app.access.permissions import Permission
from app.checks.models import KINDS
from app.checks.schemas import CheckOut, ChecksOut, ContainerOut
from app.checks.store import read_checks, read_containers
from app.collector.checks import CHECKS
from app.core.db import DbSession
from app.inventory.deps import group_of_server

router = APIRouter()

visible = Depends(require_group_visible(group=group_of_server))
EVERY = {check.kind: int(check.every) for check in CHECKS}


@router.get("/servers/{server_id}/checks", dependencies=[visible])
async def list_checks(
    server_id: UUID,
    db: DbSession,
    access: CurrentAccess,
    group_id: Annotated[UUID, Depends(group_of_server)],
) -> ChecksOut:
    rows = await read_checks(db, server_id)
    can_view_processes = access.allows(Permission.VIEW_PROCESSES, group_id)
    checks = []
    for kind in KINDS:
        row = rows.get(kind)
        if row is None:
            checks.append(
                CheckOut(
                    kind=kind, status="not_checked", checked_at=None, every_seconds=EVERY[kind], data=None, data_at=None
                )
            )
            continue
        # Without View processes, the person learns when the check ran but not what it saw.
        hidden = kind == "processes" and not can_view_processes
        checks.append(
            CheckOut(
                kind=kind,
                status=row.status,
                checked_at=row.checked_at,
                every_seconds=EVERY[kind],
                data=None if hidden else row.data,
                data_at=None if hidden else row.data_at,
            )
        )
    return ChecksOut(can_view_processes=can_view_processes, checks=checks)


@router.get("/servers/{server_id}/containers", dependencies=[visible])
async def list_containers(server_id: UUID, db: DbSession) -> list[ContainerOut]:
    return [ContainerOut.model_validate(container) for container in await read_containers(db, server_id)]

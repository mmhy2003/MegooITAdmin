"""The routes under /api/log-views: a person lists their own views and the shared ones they read, saves views, and
replaces and deletes the ones they may change. Each route checks the servers of a view against the person's own
access, so none needs a group in its path."""

from uuid import UUID

from fastapi import APIRouter, Request, Response

from app.access.deps import CurrentAccess
from app.audit import audited
from app.auth.deps import CurrentUser
from app.core.db import DbSession
from app.logs import actions, views
from app.logs.schemas import LogViewIn, LogViewOut

router = APIRouter(prefix="/log-views")


@router.get("")
async def list_views(db: DbSession, user: CurrentUser, access: CurrentAccess) -> list[LogViewOut]:
    return await views.list_views(db, access, user)


@router.post("", dependencies=[audited(actions.LOG_VIEW_CREATED)])
async def create_view(
    body: LogViewIn, request: Request, db: DbSession, user: CurrentUser, access: CurrentAccess
) -> LogViewOut:
    return await views.create_view(db, request, user, access, body)


@router.put("/{view_id}", dependencies=[audited(actions.LOG_VIEW_UPDATED)])
async def update_view(
    view_id: UUID, body: LogViewIn, request: Request, db: DbSession, user: CurrentUser, access: CurrentAccess
) -> LogViewOut:
    return await views.update_view(db, request, user, access, view_id, body)


@router.delete("/{view_id}", status_code=204, dependencies=[audited(actions.LOG_VIEW_DELETED)])
async def delete_view(
    view_id: UUID, request: Request, db: DbSession, user: CurrentUser, access: CurrentAccess
) -> Response:
    await views.delete_view(db, request, user, access, view_id)
    return Response(status_code=204)

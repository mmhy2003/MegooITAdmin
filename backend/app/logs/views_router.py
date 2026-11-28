"""The routes under /api/log-views: a person lists their own views and the shared ones they read, and saves views.
Each route checks the servers of a view against the person's own access, so none needs a group in its path."""

from fastapi import APIRouter, Request

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

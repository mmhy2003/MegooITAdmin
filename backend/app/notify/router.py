"""The routes under /api/notifications/email: the Owner reads and changes the email settings, and sends a test to
their own address."""

from fastapi import APIRouter, Depends, Request

from app.access.deps import require_owner
from app.audit import audited
from app.auth.deps import CurrentUser
from app.core.db import DbSession
from app.notify import actions, service
from app.notify.schemas import EmailIn, EmailOut, TestResultOut

email_router = APIRouter(prefix="/notifications/email")


@email_router.get("", dependencies=[Depends(require_owner)])
async def get_email(db: DbSession) -> EmailOut:
    return await service.get_email(db)


@email_router.put("", dependencies=[Depends(require_owner), audited(actions.NOTIFICATION_EMAIL_CHANGED)])
async def put_email(body: EmailIn, request: Request, db: DbSession, user: CurrentUser) -> EmailOut:
    # `user` is the Owner who changes the settings.
    return await service.put_email(db, request, user, body)


@email_router.post("/test", dependencies=[Depends(require_owner), audited(actions.NOTIFICATION_EMAIL_TESTED)])
async def test_email(request: Request, db: DbSession, user: CurrentUser) -> TestResultOut:
    # The test goes to `user`, the Owner who asks for it.
    return await service.test_email(db, request, user)

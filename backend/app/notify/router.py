"""The routes under /api/notifications/email: the Owner reads and changes the email settings, and sends a test to
their own address. Under /api/notification-channels the Owner lists, creates, changes, deletes and tests the webhook
and Telegram channels."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.access.deps import require_owner
from app.audit import audited
from app.auth.deps import CurrentUser
from app.core.db import DbSession
from app.notify import actions, service
from app.notify.schemas import ChannelIn, ChannelOut, ChannelPatch, EmailIn, EmailOut, TestResultOut

email_router = APIRouter(prefix="/notifications/email")
channels_router = APIRouter(prefix="/notification-channels")


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


@channels_router.get("", dependencies=[Depends(require_owner)])
async def list_channels(db: DbSession) -> list[ChannelOut]:
    return await service.list_channels(db)


@channels_router.post("", dependencies=[Depends(require_owner), audited(actions.NOTIFICATION_CHANNEL_CREATED)])
async def create_channel(body: ChannelIn, request: Request, db: DbSession, user: CurrentUser) -> ChannelOut:
    # `user` is the Owner who creates the channel.
    return await service.create_channel(db, request, user, body)


@channels_router.patch(
    "/{channel_id}", dependencies=[Depends(require_owner), audited(actions.NOTIFICATION_CHANNEL_CHANGED)]
)
async def update_channel(
    channel_id: UUID, body: ChannelPatch, request: Request, db: DbSession, user: CurrentUser
) -> ChannelOut:
    return await service.update_channel(db, request, user, channel_id, body)


@channels_router.delete(
    "/{channel_id}",
    status_code=204,
    dependencies=[Depends(require_owner), audited(actions.NOTIFICATION_CHANNEL_DELETED)],
)
async def delete_channel(channel_id: UUID, request: Request, db: DbSession, user: CurrentUser) -> Response:
    await service.delete_channel(db, request, user, channel_id)
    return Response(status_code=204)


@channels_router.post(
    "/{channel_id}/test", dependencies=[Depends(require_owner), audited(actions.NOTIFICATION_CHANNEL_TESTED)]
)
async def test_channel(channel_id: UUID, request: Request, db: DbSession, user: CurrentUser) -> TestResultOut:
    return await service.test_channel(db, request, user, channel_id)

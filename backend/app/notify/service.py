"""The email settings and the webhook and Telegram channels the Owner reads, changes and tests, between the routes
and the tables. The password, URLs and tokens are sealed and never leave: answers say only whether a password is saved
and a channel's hint, and events show a secret as [redacted]."""

import json
import re
import uuid
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import Result, Target, changes, record
from app.auth.crypto import SecretUndecryptable
from app.auth.models import User
from app.auth.service import actor_of, auth_event
from app.core.config import get_settings
from app.core.db import flush_unique
from app.notify import actions, transports
from app.notify.crypto import EMAIL_ROW, seal, unseal
from app.notify.messages import TEST_TEXT
from app.notify.models import NotificationChannel, NotificationDelivery, NotificationEmail
from app.notify.schemas import (
    ChannelIn,
    ChannelOut,
    ChannelPatch,
    DeliveryOut,
    EmailIn,
    EmailOut,
    TestResultOut,
)

EMAIL_FIELDS = (
    "enabled",
    "host",
    "port",
    "security",
    "username",
    "from_name",
    "from_address",
    "extra_addresses",
    "min_severity",
)
EMAIL_TARGET = Target(type="notification_email", id="1", name="Email")
TEST_SUBJECT = "MegooITAdmin test"


def delivery_out(delivery: NotificationDelivery | None) -> DeliveryOut | None:
    if delivery is None:
        return None
    # A failed delivery keeps the time its last try was due.
    at = delivery.delivered_at if delivery.state == "delivered" else delivery.next_attempt_at
    return DeliveryOut(state=delivery.state, at=at, error=delivery.last_error)


async def _email(db: AsyncSession, *, for_update: bool = False) -> NotificationEmail:
    query = select(NotificationEmail).where(NotificationEmail.id == 1)
    return (await db.scalars(query.with_for_update() if for_update else query)).one()


async def _email_out(db: AsyncSession, email: NotificationEmail) -> EmailOut:
    last = await db.scalar(
        select(NotificationDelivery)
        .where(NotificationDelivery.channel_id.is_(None))
        .order_by(NotificationDelivery.created_at.desc(), NotificationDelivery.id.desc())
        .limit(1)
    )
    return EmailOut(
        **{field: getattr(email, field) for field in EMAIL_FIELDS},
        password_set=email.password is not None,
        last_delivery=delivery_out(last),
    )


def _audited(email: NotificationEmail, password: Any) -> dict[str, Any]:
    """The fields an event compares. password is a marker that differs when the password changes; changes()
    redacts it either way."""
    values = {field: getattr(email, field) for field in EMAIL_FIELDS}
    return values | {"extra_addresses": list(email.extra_addresses), "password": password}


async def get_email(db: AsyncSession) -> EmailOut:
    return await _email_out(db, await _email(db))


async def put_email(db: AsyncSession, request: Request, owner: User, body: EmailIn) -> EmailOut:
    email = await _email(db, for_update=True)
    kept = None if email.password is None else "saved"
    before = _audited(email, kept)
    for field in EMAIL_FIELDS:
        setattr(email, field, getattr(body, field))
    if body.password == "":
        email.password, password = None, None
    elif body.password is not None:
        email.password, password = seal(body.password, EMAIL_ROW), "replaced"
    else:
        password = kept
    change = changes(before, _audited(email, password))
    email.updated_at = func.now()
    await db.flush()
    await db.refresh(email)
    out = await _email_out(db, email)
    # record() last: it holds the audit chain lock until the commit.
    await record(
        db,
        auth_event(
            request, actions.NOTIFICATION_EMAIL_CHANGED, actor_of(owner), mfa=True, target=EMAIL_TARGET, change=change
        ),
    )
    return out


async def test_email(db: AsyncSession, request: Request, owner: User) -> TestResultOut:
    """Sends the test message to the Owner's own address. A failure is an answer too, and is recorded."""
    email = await _email(db)
    if email.host is None or email.from_address is None:
        raise HTTPException(409, "email_not_set_up")
    error = None
    try:
        password = "" if email.password is None else unseal(email.password, EMAIL_ROW)
        config = transports.EmailConfig(
            host=email.host,
            port=email.port,
            security=email.security,
            username=email.username or "",
            password=password,
            from_name=email.from_name,
            from_address=email.from_address,
        )
        await transports.send_email(config, [owner.email], TEST_SUBJECT, TEST_TEXT)
    except SecretUndecryptable:
        error = "undecryptable"
    except transports.DeliveryFailed as failed:
        error = failed.code
    out = TestResultOut(ok=error is None, error=error)
    await record(
        db,
        auth_event(
            request,
            actions.NOTIFICATION_EMAIL_TESTED,
            actor_of(owner),
            mfa=True,
            target=EMAIL_TARGET,
            result=Result.SUCCESS if out.ok else Result.FAILURE,
            detail=out.model_dump(),
        ),
    )
    return out


MAX_CHANNELS = 20
MAX_URL = 2048
TOKEN_PATTERN = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
CHAT_PATTERN = re.compile(r"^(-?\d{1,20}|@[A-Za-z0-9_]{5,32})$")
CHANNEL_FIELDS = ("name", "kind", "min_severity", "enabled")
# The parts of each kind's secret.
SECRET_KEYS = {"webhook_json": ("url",), "webhook_slack": ("url",), "telegram": ("bot_token", "chat_id")}


def _channel_target(channel: NotificationChannel) -> Target:
    return Target(type="notification_channel", id=str(channel.id), name=channel.name)


def _channel_audited(channel: NotificationChannel, secret: Any) -> dict[str, Any]:
    """The fields an event compares. secret is a marker that differs when the secret changes; changes() redacts it
    either way."""
    return {field: getattr(channel, field) for field in CHANNEL_FIELDS} | {"hint": channel.hint, "secret": secret}


def _checked_secret(kind: str, secret: dict[str, str | None]) -> tuple[dict[str, str], str]:
    """The secret of a channel of the kind, checked, and the hint the pages show of it. 422 with a code otherwise:
    the value sent is never echoed back."""
    if kind == "telegram":
        token, chat = secret.get("bot_token"), secret.get("chat_id")
        if token is None or len(token) > 200 or not TOKEN_PATTERN.match(token):
            raise HTTPException(422, "bad_telegram_token")
        if chat is None or not CHAT_PATTERN.match(chat):
            raise HTTPException(422, "bad_chat_id")
        return {"bot_token": token, "chat_id": chat}, f"chat {chat}"
    url = secret.get("url")
    if url is None or len(url) > MAX_URL:
        raise HTTPException(422, "bad_url")
    try:
        transports.check_url(url, get_settings().webhook_allow_http)
    except transports.DeliveryFailed as refused:
        raise HTTPException(422, refused.code) from None
    return {"url": url}, urlsplit(url).hostname


def _sent_secret(kind: str, body: ChannelIn | ChannelPatch) -> dict[str, str]:
    return {key: getattr(body, key) for key in SECRET_KEYS[kind] if getattr(body, key) is not None}


async def _check_channel_name(db: AsyncSession, name: str, channel_id: UUID | None = None) -> None:
    """Another channel with the name, without regard to case: 409."""
    query = select(NotificationChannel.id).where(func.lower(NotificationChannel.name) == name.lower())
    if channel_id is not None:
        query = query.where(NotificationChannel.id != channel_id)
    if await db.scalar(query) is not None:
        raise HTTPException(409, "channel_name_taken")


async def _last_deliveries(db: AsyncSession, channel_ids: list[UUID]) -> dict[UUID, NotificationDelivery]:
    """The newest delivery of each channel."""
    query = (
        select(NotificationDelivery)
        .where(NotificationDelivery.channel_id.in_(channel_ids))
        .ext(distinct_on(NotificationDelivery.channel_id))
        .order_by(
            NotificationDelivery.channel_id, NotificationDelivery.created_at.desc(), NotificationDelivery.id.desc()
        )
    )
    return {delivery.channel_id: delivery for delivery in (await db.scalars(query)).all()}


def _channel_out(channel: NotificationChannel, last: NotificationDelivery | None) -> ChannelOut:
    return ChannelOut(
        **{field: getattr(channel, field) for field in CHANNEL_FIELDS},
        id=channel.id,
        hint=channel.hint,
        created_at=channel.created_at,
        updated_at=channel.updated_at,
        last_delivery=delivery_out(last),
    )


async def _channel_out_of(db: AsyncSession, channel: NotificationChannel) -> ChannelOut:
    return _channel_out(channel, (await _last_deliveries(db, [channel.id])).get(channel.id))


async def _channel(db: AsyncSession, channel_id: UUID, *, for_update: bool = False) -> NotificationChannel:
    query = select(NotificationChannel).where(NotificationChannel.id == channel_id)
    channel = await db.scalar(query.with_for_update() if for_update else query)
    if channel is None:
        raise HTTPException(404, "not_found")
    return channel


async def list_channels(db: AsyncSession) -> list[ChannelOut]:
    """Every channel, by name, with its newest delivery."""
    query = select(NotificationChannel).order_by(func.lower(NotificationChannel.name), NotificationChannel.id)
    channels = list((await db.scalars(query)).all())
    last = await _last_deliveries(db, [channel.id for channel in channels])
    return [_channel_out(channel, last.get(channel.id)) for channel in channels]


async def create_channel(db: AsyncSession, request: Request, owner: User, body: ChannelIn) -> ChannelOut:
    secret, hint = _checked_secret(body.kind, _sent_secret(body.kind, body))
    if await db.scalar(select(func.count()).select_from(NotificationChannel)) >= MAX_CHANNELS:
        raise HTTPException(409, "too_many_channels")
    await _check_channel_name(db, body.name)
    # The ID first: the secret is sealed to it.
    channel_id = uuid.uuid4()
    channel = NotificationChannel(
        id=channel_id,
        **body.model_dump(include=set(CHANNEL_FIELDS)),
        secret=seal(json.dumps(secret), channel_id.bytes),
        hint=hint,
    )
    db.add(channel)
    await flush_unique(db, "notification_channels_name_key", "channel_name_taken")
    await db.refresh(channel)
    out = await _channel_out_of(db, channel)
    # record() last: it holds the audit chain lock until the commit.
    await record(
        db,
        auth_event(
            request,
            actions.NOTIFICATION_CHANNEL_CREATED,
            actor_of(owner),
            mfa=True,
            target=_channel_target(channel),
            change=changes({}, _channel_audited(channel, "saved")),
        ),
    )
    return out


async def update_channel(
    db: AsyncSession, request: Request, owner: User, channel_id: UUID, body: ChannelPatch
) -> ChannelOut:
    """Changes the fields sent. A secret part sent replaces that part; the others are kept, as far as the kind they
    were saved for has them."""
    channel = await _channel(db, channel_id, for_update=True)
    before = _channel_audited(channel, "saved")
    kind = body.kind or channel.kind
    try:
        saved = json.loads(unseal(channel.secret, channel.id.bytes))
    except SecretUndecryptable:
        saved = {}
    kept = {key: saved[key] for key in SECRET_KEYS[kind] if key in saved}
    secret, hint = _checked_secret(kind, kept | _sent_secret(kind, body))
    if body.name is not None and body.name != channel.name:
        await _check_channel_name(db, body.name, channel.id)
    for field in CHANNEL_FIELDS:
        if getattr(body, field) is not None:
            setattr(channel, field, getattr(body, field))
    marker = "saved"
    if secret != saved:
        channel.secret, marker = seal(json.dumps(secret), channel.id.bytes), "replaced"
    channel.hint = hint
    change = changes(before, _channel_audited(channel, marker))
    channel.updated_at = func.now()
    await flush_unique(db, "notification_channels_name_key", "channel_name_taken")
    await db.refresh(channel)
    out = await _channel_out_of(db, channel)
    await record(
        db,
        auth_event(
            request,
            actions.NOTIFICATION_CHANNEL_CHANGED,
            actor_of(owner),
            mfa=True,
            # The channel as it is named now; the change holds the old name.
            target=_channel_target(channel),
            change=change,
        ),
    )
    return out


async def delete_channel(db: AsyncSession, request: Request, owner: User, channel_id: UUID) -> None:
    """Deletes the channel, and its deliveries with it."""
    channel = await _channel(db, channel_id, for_update=True)
    deleted = auth_event(
        request,
        actions.NOTIFICATION_CHANNEL_DELETED,
        actor_of(owner),
        mfa=True,
        target=_channel_target(channel),
        change=changes(_channel_audited(channel, "saved"), {}),
    )
    await db.delete(channel)
    await db.flush()
    await record(db, deleted)


async def _send_test(channel: NotificationChannel) -> None:
    try:
        secret = json.loads(unseal(channel.secret, channel.id.bytes))
    except SecretUndecryptable:
        raise transports.DeliveryFailed("undecryptable") from None
    allow_http = get_settings().webhook_allow_http
    if channel.kind == "webhook_json":
        payload = {"version": 1, "event": "test", "text": TEST_TEXT}
        await transports.post_json(secret["url"], payload, allow_http=allow_http)
    elif channel.kind == "webhook_slack":
        await transports.post_json(secret["url"], {"text": TEST_TEXT}, allow_http=allow_http)
    else:
        await transports.send_telegram(secret["bot_token"], secret["chat_id"], TEST_TEXT)


async def test_channel(db: AsyncSession, request: Request, owner: User, channel_id: UUID) -> TestResultOut:
    """Sends the test message to the channel, switched on or not. A failure is an answer too, and is recorded."""
    channel = await _channel(db, channel_id)
    error = None
    try:
        await _send_test(channel)
    except transports.DeliveryFailed as failed:
        error = failed.code
    out = TestResultOut(ok=error is None, error=error)
    await record(
        db,
        auth_event(
            request,
            actions.NOTIFICATION_CHANNEL_TESTED,
            actor_of(owner),
            mfa=True,
            target=_channel_target(channel),
            result=Result.SUCCESS if out.ok else Result.FAILURE,
            detail=out.model_dump(),
        ),
    )
    return out

"""The email settings the Owner reads, changes and tests, between the routes and the tables. The password is sealed
and never leaves: answers say only whether one is saved, and events show it as [redacted]."""

from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import Result, Target, changes, record
from app.auth.crypto import SecretUndecryptable
from app.auth.models import User
from app.auth.service import actor_of, auth_event
from app.notify import actions, transports
from app.notify.crypto import EMAIL_ROW, seal, unseal
from app.notify.messages import TEST_TEXT
from app.notify.models import NotificationDelivery, NotificationEmail
from app.notify.schemas import DeliveryOut, EmailIn, EmailOut, TestResultOut

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

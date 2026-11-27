"""The backend's sender of alert messages. It dispatches each new alert event into one delivery per matching channel
(and one for email), then sends the due deliveries, each in its own transaction that holds the delivery's row, so two
senders never send the same one. A failed try is retried on RETRY_DELAYS, and given up after MAX_ATTEMPTS."""

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.access.models import RoleGrant
from app.alerts.models import Alert, AlertEvent
from app.auth.crypto import SecretUndecryptable
from app.auth.models import User
from app.core.config import Settings, get_settings
from app.inventory.models import Server, ServerGroup
from app.notify import messages, transports
from app.notify.crypto import EMAIL_ROW, unseal
from app.notify.messages import EventView
from app.notify.models import NotificationChannel, NotificationDelivery, NotificationEmail
from app.notify.transports import DeliveryFailed, EmailConfig

logger = logging.getLogger(__name__)

# Seconds to wait after tries 1 to 5. The sixth failed try gives up.
RETRY_DELAYS = (30, 120, 300, 900, 2400)
MAX_ATTEMPTS = 6
EVERY = 5.0
# An event the sender first sees later than this (the backend was down) is dispatched without deliveries.
TOO_OLD = timedelta(hours=1)
KEEP = timedelta(days=30)
BATCH = 50
PRUNE_EVERY = timedelta(hours=1)


def _matches(min_severity: str, severity: str) -> bool:
    return min_severity == "warning" or severity == "critical"


async def email_recipients(db: AsyncSession, server_group_id: UUID) -> list[str]:
    """The Owners and the group's Admins whose accounts are not disabled, plus the extra addresses of the email
    settings: lowercased, sorted, each once."""
    admin_here = exists().where(
        RoleGrant.user_id == User.id, RoleGrant.server_group_id == server_group_id, RoleGrant.role == "admin"
    )
    query = select(User.email).where(User.disabled_at.is_(None), or_(User.platform_role == "owner", admin_here))
    accounts = (await db.scalars(query)).all()
    extra = await db.scalar(select(NotificationEmail.extra_addresses).where(NotificationEmail.id == 1)) or []
    return sorted({address.lower() for address in [*accounts, *extra]})


def _failed(delivery: NotificationDelivery, code: str, now: datetime) -> None:
    """Counts a failed try: the delivery is retried on RETRY_DELAYS, or failed after MAX_ATTEMPTS."""
    delivery.attempts += 1
    delivery.last_error = code
    if delivery.attempts >= MAX_ATTEMPTS:
        delivery.state = "failed"
    else:
        delivery.next_attempt_at = now + timedelta(seconds=RETRY_DELAYS[delivery.attempts - 1])


class Sender:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        settings: Settings | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessions
        self._settings = settings or get_settings()
        self._clock = clock

    async def dispatch(self) -> int:
        """Queues the deliveries of every undispatched event, oldest first, BATCH events per transaction. Returns how
        many events it dispatched."""
        total = 0
        while count := await self._dispatch_batch():
            total += count
            if count < BATCH:
                break
        return total

    async def _dispatch_batch(self) -> int:
        now = self._clock()
        async with self._sessions() as db:
            query = (
                select(AlertEvent.id, AlertEvent.at, Alert.severity)
                .join(Alert, Alert.id == AlertEvent.alert_id)
                .where(AlertEvent.dispatched_at.is_(None))
                .order_by(AlertEvent.at, AlertEvent.id)
                .limit(BATCH)
                # Only the events are locked: the API role may not lock alerts.
                .with_for_update(of=AlertEvent, skip_locked=True)
            )
            events = (await db.execute(query)).all()
            if not events:
                return 0
            channels = (
                await db.execute(
                    select(NotificationChannel.id, NotificationChannel.min_severity).where(NotificationChannel.enabled)
                )
            ).all()
            email = await db.scalar(select(NotificationEmail).where(NotificationEmail.id == 1))
            targets: list[tuple[UUID | None, str]] = list(channels)
            if email is not None and email.enabled:
                targets.append((None, email.min_severity))
            rows = [
                {"event_id": event_id, "channel_id": channel_id, "state": "pending", "next_attempt_at": now,
                 "created_at": now}
                for event_id, at, severity in events
                if now - at <= TOO_OLD
                for channel_id, min_severity in targets
                if _matches(min_severity, severity)
            ]
            if rows:
                await db.execute(insert(NotificationDelivery).on_conflict_do_nothing(), rows)
            ids = [event_id for event_id, _, _ in events]
            await db.execute(update(AlertEvent).where(AlertEvent.id.in_(ids)).values(dispatched_at=now))
            await db.commit()
            return len(events)

    async def send_due(self) -> int:
        """Tries the due deliveries, one transaction each, at most BATCH of them. Returns how many it tried."""
        tried = 0
        while tried < BATCH and await self._send_one():
            tried += 1
        return tried

    async def _send_one(self) -> bool:
        now = self._clock()
        async with self._sessions() as db:
            query = (
                select(NotificationDelivery)
                .where(NotificationDelivery.state == "pending", NotificationDelivery.next_attempt_at <= now)
                .order_by(NotificationDelivery.next_attempt_at, NotificationDelivery.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            delivery = await db.scalar(query)
            if delivery is None:
                return False
            try:
                await self._deliver(db, delivery)
            except DeliveryFailed as failure:
                _failed(delivery, failure.code, now)
            except Exception:
                # A bug or a row of an unexpected shape: it counts as a try, so the deliveries behind it still go.
                logger.exception("Could not send delivery %s", delivery.id)
                delivery_id = delivery.id
                # The transaction may be aborted: the row is read again, still held, in a new one.
                await db.rollback()
                delivery = await db.scalar(query.where(NotificationDelivery.id == delivery_id))
                if delivery is None:
                    return True  # another sender holds it now
                _failed(delivery, "internal", now)
            else:
                delivery.state = "delivered"
                delivery.delivered_at = now
            await db.commit()
            return True

    async def _deliver(self, db: AsyncSession, delivery: NotificationDelivery) -> None:
        view, server_group_id = await _event_view(db, delivery.event_id)
        if delivery.channel_id is None:
            await self._send_email(db, view, server_group_id)
            return
        channel = await db.get(NotificationChannel, delivery.channel_id)
        try:
            secret = json.loads(unseal(channel.secret, channel.id.bytes))
        except SecretUndecryptable:
            raise DeliveryFailed("undecryptable") from None
        allow_http = self._settings.webhook_allow_http
        if channel.kind == "webhook_json":
            await transports.post_json(secret["url"], messages.generic_json(view), allow_http=allow_http)
        elif channel.kind == "webhook_slack":
            await transports.post_json(secret["url"], {"text": messages.chat_text(view)}, allow_http=allow_http)
        else:
            await transports.send_telegram(secret["bot_token"], secret["chat_id"], messages.chat_text(view))

    async def _send_email(self, db: AsyncSession, view: EventView, server_group_id: UUID) -> None:
        email = await db.scalar(select(NotificationEmail).where(NotificationEmail.id == 1))
        if email.host is None or email.from_address is None:
            raise DeliveryFailed("email_not_set_up")
        try:
            password = "" if email.password is None else unseal(email.password, EMAIL_ROW)
        except SecretUndecryptable:
            raise DeliveryFailed("undecryptable") from None
        config = EmailConfig(
            host=email.host,
            port=email.port,
            security=email.security,
            username=email.username or "",
            password=password,
            from_name=email.from_name,
            from_address=email.from_address,
        )
        recipients = await email_recipients(db, server_group_id)
        await transports.send_email(config, recipients, messages.email_subject(view), messages.email_body(view))

    async def prune(self) -> int:
        """Deletes the deliveries created more than KEEP ago. Returns how many."""
        async with self._sessions() as db:
            result = await db.execute(
                delete(NotificationDelivery).where(NotificationDelivery.created_at < self._clock() - KEEP)
            )
            await db.commit()
            return result.rowcount

    async def run(self) -> None:
        """Dispatches, sends and (once an hour) prunes every EVERY seconds until cancelled. A failure is logged and the
        loop goes on."""
        pruned_at: datetime | None = None
        while True:
            try:
                await self.dispatch()
                await self.send_due()
                if pruned_at is None or self._clock() - pruned_at >= PRUNE_EVERY:
                    await self.prune()
                    pruned_at = self._clock()
            except Exception:
                # The exception is the database's or a bug's: the transports never carry a secret in theirs.
                logger.exception("The notification sender failed, will retry")
            await asyncio.sleep(EVERY)


async def _event_view(db: AsyncSession, event_id: UUID) -> tuple[EventView, UUID]:
    """The event as the messages tell it, and its server's group, in one query."""
    query = (
        select(AlertEvent, Alert, Server.name, Server.server_group_id, ServerGroup.name)
        .join(Alert, Alert.id == AlertEvent.alert_id)
        .join(Server, Server.id == Alert.server_id)
        .join(ServerGroup, ServerGroup.id == Server.server_group_id)
        .where(AlertEvent.id == event_id)
    )
    event, alert, server_name, server_group_id, group_name = (await db.execute(query)).one()
    view = EventView(
        event_id=event.id,
        kind=event.kind,
        at=event.at,
        alert_id=alert.id,
        severity=alert.severity,
        rule_name=alert.rule_name,
        metric=alert.metric,
        comparison=alert.comparison,
        threshold=alert.threshold,
        duration_seconds=alert.duration_seconds,
        instance=alert.instance,
        value=alert.value,
        last_value=alert.last_value,
        fired_at=alert.fired_at,
        resolved_at=alert.resolved_at,
        end_reason=alert.end_reason,
        server_id=alert.server_id,
        server_name=server_name,
        group_name=group_name,
    )
    return view, server_group_id

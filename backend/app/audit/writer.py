"""The writer: an event is inserted in the caller's transaction and chained to the one before it."""

from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.chain import event_hash
from app.audit.events import Event
from app.audit.models import AuditChainHead, AuditEvent
from app.core.db import SessionLocal

AUDIT_ACTIONS = "audit_actions"  # key in session.info: set[str] of actions recorded in this session
LOCK_TIMEOUT = "5s"
LOCK_NOT_AVAILABLE = "55P03"


class AuditChainBusy(RuntimeError):
    """The head of the chain stayed locked longer than LOCK_TIMEOUT."""


async def record(session: AsyncSession, event: Event) -> AuditEvent:
    """Adds the event to the session's transaction and moves the head of the chain to it. Never commits.

    Call it last in the transaction: the head stays locked until the commit, so concurrent writers wait.
    """
    try:
        previous = (
            await session.execute(
                text("SELECT current_setting('lock_timeout'), set_config('lock_timeout', :timeout, true)"),
                {"timeout": LOCK_TIMEOUT},
            )
        ).first()[0]
        head = (
            await session.execute(
                select(AuditChainHead)
                .where(AuditChainHead.id == 1)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        await session.execute(text("SELECT set_config('lock_timeout', :timeout, true)"), {"timeout": previous})
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == LOCK_NOT_AVAILABLE:
            raise AuditChainBusy(f"the audit chain stayed locked for {LOCK_TIMEOUT}") from exc
        raise
    now = datetime.now(UTC)
    now = now.replace(microsecond=now.microsecond // 1000 * 1000)
    if head.time is not None and now < head.time:
        now = head.time  # times never decrease along the chain
    columns = event.columns()
    seq = head.seq + 1
    digest = event_hash(seq, now, head.hash, columns)
    row = AuditEvent(seq=seq, time=now, prev_hash=head.hash, hash=digest, **columns)
    session.add(row)
    head.seq, head.hash, head.time = seq, digest, now
    await session.flush()
    session.info.setdefault(AUDIT_ACTIONS, set()).add(event.action)
    return row


async def record_alone(event: Event) -> AuditEvent:
    """Records the event in a session of its own and commits it, so the caller's rollback cannot take it away.
    For refused actions, such as a failed sign-in."""
    async with SessionLocal() as session:
        row = await record(session, event)
        await session.commit()
        return row

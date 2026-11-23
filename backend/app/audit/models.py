"""The audit tables: the append-only, hash-chained audit_log and the one-row head of its chain.

audit_log has no foreign keys: an event keeps the IDs and names as they were, so it survives their deletion.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    LargeBinary,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AuditEvent(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        # (seq, time): a unique index on a hypertable must hold its partitioning column. The head lock keeps seq unique.
        PrimaryKeyConstraint("seq", "time", name="audit_log_pkey"),
        CheckConstraint("actor_type IN ('human', 'agent', 'system')", name="audit_log_actor_type_check"),
        CheckConstraint(r"action ~ '^[a-z0-9_]+(\.[a-z0-9_]+)+$'", name="audit_log_action_check"),
        CheckConstraint("result IN ('success', 'failure', 'error')", name="audit_log_result_check"),
        CheckConstraint(
            "risk_class IN ('platform_read', 'server_read', 'change', 'destructive', 'forbidden')",
            name="audit_log_risk_class_check",
        ),
        CheckConstraint(
            "octet_length(prev_hash) = 32 AND octet_length(hash) = 32", name="audit_log_hash_length_check"
        ),
    )

    seq: Mapped[int] = mapped_column(BigInteger, autoincrement=False)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_type: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str | None] = mapped_column(Text)
    actor_name: Mapped[str] = mapped_column(Text)
    actor_details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    on_behalf_of_id: Mapped[str | None] = mapped_column(Text)
    on_behalf_of_name: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[str | None] = mapped_column(Text)
    target_name: Mapped[str | None] = mapped_column(Text)
    context: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    source_ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    auth_method: Mapped[str | None] = mapped_column(Text)
    mfa: Mapped[bool | None] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text)
    change: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[str] = mapped_column(Text)
    result_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    risk_class: Mapped[str | None] = mapped_column(Text)
    prev_hash: Mapped[bytes] = mapped_column(LargeBinary)
    hash: Mapped[bytes] = mapped_column(LargeBinary)


Index("audit_log_time_idx", AuditEvent.time.desc())


class AuditChainHead(Base):
    """The number, hash and time of the newest event. The writer locks this one row to number events without gaps."""

    __tablename__ = "audit_chain_head"
    __table_args__ = (CheckConstraint("id = 1", name="audit_chain_head_id_check"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    seq: Mapped[int] = mapped_column(BigInteger)
    hash: Mapped[bytes] = mapped_column(LargeBinary)
    time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# The columns an event's hash covers, besides seq, time and prev_hash. Event.columns() gives exactly these.
CHAINED_COLUMNS: tuple[str, ...] = tuple(
    c.name for c in AuditEvent.__table__.columns if c.name not in {"seq", "time", "prev_hash", "hash"}
)

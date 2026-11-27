"""The webhook and Telegram channels, the email settings, and the delivery of each alert event to each of them."""

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class NotificationChannel(Base):
    """A webhook or a Telegram chat. Its URL, or its bot token and chat, is sealed in secret and never shown again."""

    __tablename__ = "notification_channels"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="notification_channels_pkey"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="notification_channels_name_check"),
        CheckConstraint(
            "kind IN ('webhook_json', 'webhook_slack', 'telegram')", name="notification_channels_kind_check"
        ),
        CheckConstraint("min_severity IN ('warning', 'critical')", name="notification_channels_min_severity_check"),
        # Names are unique without regard to case.
        Index("notification_channels_name_key", text("lower(name)"), unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    min_severity: Mapped[str] = mapped_column(Text, server_default=text("'warning'"))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    secret: Mapped[bytes] = mapped_column(LargeBinary)
    # What the pages show of the secret ("hooks.slack.com/…/x9Q").
    hint: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationEmail(Base):
    """The email settings: one row, inserted by the migration, switched off until the Owner sets it up."""

    __tablename__ = "notification_email"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="notification_email_pkey"),
        CheckConstraint("id = 1", name="notification_email_id_check"),
        CheckConstraint("port BETWEEN 1 AND 65535", name="notification_email_port_check"),
        CheckConstraint("security IN ('starttls', 'tls', 'none')", name="notification_email_security_check"),
        CheckConstraint("cardinality(extra_addresses) <= 20", name="notification_email_extra_addresses_check"),
        CheckConstraint("min_severity IN ('warning', 'critical')", name="notification_email_min_severity_check"),
        CheckConstraint(
            "NOT enabled OR (host IS NOT NULL AND from_address IS NOT NULL)", name="notification_email_ready_check"
        ),
    )

    id: Mapped[int] = mapped_column(SmallInteger, autoincrement=False)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    host: Mapped[str | None] = mapped_column(Text)
    port: Mapped[int] = mapped_column(Integer, server_default=text("587"))
    security: Mapped[str] = mapped_column(Text, server_default=text("'starttls'"))
    username: Mapped[str | None] = mapped_column(Text)
    # Sealed with the notification key.
    password: Mapped[bytes | None] = mapped_column(LargeBinary)
    from_name: Mapped[str] = mapped_column(Text, server_default=text("'MegooITAdmin'"))
    from_address: Mapped[str | None] = mapped_column(Text)
    # Up to 20 addresses that get every alert, besides the Owner and the Admins of the server's group.
    extra_addresses: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    min_severity: Mapped[str] = mapped_column(Text, server_default=text("'warning'"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationDelivery(Base):
    """One alert event sent to one channel, or by email when channel_id is None, with its tries."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="notification_deliveries_pkey"),
        ForeignKeyConstraint(
            ["event_id"], ["alert_events.id"], ondelete="CASCADE", name="notification_deliveries_event_id_fkey"
        ),
        ForeignKeyConstraint(
            ["channel_id"],
            ["notification_channels.id"],
            ondelete="CASCADE",
            name="notification_deliveries_channel_id_fkey",
        ),
        CheckConstraint("state IN ('pending', 'delivered', 'failed')", name="notification_deliveries_state_check"),
        # One delivery per event and channel, and one email per event.
        UniqueConstraint(
            "event_id",
            "channel_id",
            name="notification_deliveries_event_channel_key",
            postgresql_nulls_not_distinct=True,
        ),
        Index("notification_deliveries_due_idx", "next_attempt_at", postgresql_where=text("state = 'pending'")),
        Index("notification_deliveries_channel_id_idx", "channel_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    state: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # The error code of the last failed try.
    last_error: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

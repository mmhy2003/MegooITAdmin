"""The log file allowlist (the path patterns a group's servers may stream with tail -F) and saved log views."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class LogFileAllowlist(Base):
    """One pattern of a server group. A pattern is added or removed, never changed in place."""

    __tablename__ = "log_file_allowlist"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="log_file_allowlist_pkey"),
        ForeignKeyConstraint(
            ["server_group_id"],
        ["server_groups.id"],
        ondelete="CASCADE",
        name="log_file_allowlist_server_group_id_fkey",
        ),
        UniqueConstraint("server_group_id", "pattern", name="log_file_allowlist_server_group_id_pattern_key"),
        CheckConstraint("char_length(pattern) BETWEEN 2 AND 255", name="log_file_allowlist_pattern_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    server_group_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    pattern: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LogView(Base):
    """A person's saved view: the sources and settings of the viewer under a name, private or shared."""

    __tablename__ = "log_views"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="log_views_pkey"),
        ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE", name="log_views_owner_id_fkey"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="log_views_name_check"),
        Index("log_views_owner_id_name_key", "owner_id", text("lower(name)"), unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(Text)
    shared: Mapped[bool] = mapped_column(Boolean, server_default=false())
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

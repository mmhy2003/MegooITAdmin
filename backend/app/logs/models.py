"""The log file allowlist: the path patterns a group's servers may stream with tail -F."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
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

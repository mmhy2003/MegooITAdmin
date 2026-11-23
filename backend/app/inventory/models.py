"""Server groups: the unit roles and grants are given for."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, PrimaryKeyConstraint, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ServerGroup(Base):
    __tablename__ = "server_groups"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="server_groups_pkey"),
        # Names are unique without regard to case.
        Index("server_groups_name_key", text("lower(name)"), unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

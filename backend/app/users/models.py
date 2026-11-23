"""The open invite of an account that has not chosen its password yet. Only the token's SHA-256 is stored."""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    LargeBinary,
    PrimaryKeyConstraint,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class UserInvite(Base):
    """One open invite per account: a new link replaces the old one."""

    __tablename__ = "user_invites"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", name="user_invites_pkey"),
        ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="user_invites_user_id_fkey"),
        UniqueConstraint("token_hash", name="user_invites_token_hash_key"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

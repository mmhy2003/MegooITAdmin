"""The auth tables: accounts, their sessions and recovery codes, and the one-time setup code of a fresh install.

Secrets are never stored in the clear: passwords as Argon2id hashes, TOTP secrets encrypted with AUTH_SECRET_KEY,
session tokens and recovery and setup codes as SHA-256 hashes.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="users_pkey"),
        UniqueConstraint("email", name="users_email_key"),
        CheckConstraint("email = lower(email)", name="users_email_lower_check"),
        ForeignKeyConstraint(["platform_role"], ["roles.key"], name="users_platform_role_fkey"),
        CheckConstraint("platform_role IN ('owner', 'auditor')", name="users_platform_role_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    # None for an invited account until its link is used.
    password_hash: Mapped[str | None] = mapped_column(Text)
    # owner or auditor: platform-wide. None: the person's rights are their roles per server group.
    platform_role: Mapped[str | None] = mapped_column(Text)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    totp_secret: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_pending_secret: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The newest accepted TOTP time step: a code of this step or an older one is refused (no replay).
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)
    failed_attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthSession(Base):
    """A signed-in browser. Only the SHA-256 hash of its cookie token is stored."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="auth_sessions_pkey"),
        ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="auth_sessions_user_id_fkey"),
        UniqueConstraint("token_hash", name="auth_sessions_token_hash_key"),
        CheckConstraint("stage IN ('pending', 'active')", name="auth_sessions_stage_check"),
        CheckConstraint("mfa_method IN ('totp', 'recovery_code')", name="auth_sessions_mfa_method_check"),
        Index("auth_sessions_user_id_idx", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary)
    # pending: the password is right, the second factor is still to come. active: both are done.
    stage: Mapped[str] = mapped_column(Text)
    mfa_method: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)

    # lazy="raise": async code cannot load it on access, so a lookup loads it with joinedload.
    user: Mapped[User] = relationship(User, lazy="raise")


class RecoveryCode(Base):
    """One unused recovery code of an account, as a SHA-256 hash. Using a code deletes its row."""

    __tablename__ = "recovery_codes"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="recovery_codes_pkey"),
        ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="recovery_codes_user_id_fkey"),
        UniqueConstraint("code_hash", name="recovery_codes_code_hash_key"),
        Index("recovery_codes_user_id_idx", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    code_hash: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SetupCode(Base):
    """The one-time code from the host that claims a fresh install. One row at most."""

    __tablename__ = "auth_setup"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="auth_setup_pkey"),
        CheckConstraint("id = 1", name="auth_setup_id_check"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, autoincrement=False)
    code_hash: Mapped[bytes] = mapped_column(LargeBinary)
    failed_attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

"""The roles and each person's role per server group, with its seven grant switches."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.access.permissions import Permission
from app.core.db import Base


class Role(Base):
    """One of the four roles. Owner and Auditor are platform-wide, Admin and Operator are given per group."""

    __tablename__ = "roles"
    __table_args__ = (
        PrimaryKeyConstraint("key", name="roles_pkey"),
        CheckConstraint("scope IN ('platform', 'group')", name="roles_scope_check"),
    )

    key: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(SmallInteger)


def _switch() -> Mapped[bool]:
    return mapped_column(Boolean, server_default=text("false"))


class RoleGrant(Base):
    """A person's role in one server group, and which of the seven grants it holds there."""

    __tablename__ = "role_grants"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="role_grants_pkey"),
        ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="role_grants_user_id_fkey"),
        ForeignKeyConstraint(
            ["server_group_id"], ["server_groups.id"], ondelete="CASCADE", name="role_grants_server_group_id_fkey"
        ),
        ForeignKeyConstraint(["role"], ["roles.key"], name="role_grants_role_fkey"),
        UniqueConstraint("user_id", "server_group_id", name="role_grants_user_id_server_group_id_key"),
        CheckConstraint("role IN ('admin', 'operator')", name="role_grants_role_check"),
        # PRD §14.1: an Operator never manages playbooks.
        CheckConstraint("role = 'admin' OR NOT manage_playbooks", name="role_grants_manage_playbooks_check"),
        Index("role_grants_server_group_id_idx", "server_group_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    server_group_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    role: Mapped[str] = mapped_column(Text)
    connect_ssh: Mapped[bool] = _switch()
    connect_rdp: Mapped[bool] = _switch()
    view_logs: Mapped[bool] = _switch()
    view_processes: Mapped[bool] = _switch()
    manage_processes: Mapped[bool] = _switch()
    run_playbooks: Mapped[bool] = _switch()
    manage_playbooks: Mapped[bool] = _switch()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def fields(self) -> dict[str, str | bool]:
        """The role and the seven switches, as audit events compare them."""
        return {"role": self.role, **{p.value: getattr(self, p.value) for p in Permission}}

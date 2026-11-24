"""Server groups, the unit roles and grants are given for, and the servers in them with their tags."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
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


class Server(Base):
    __tablename__ = "servers"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="servers_pkey"),
        # No cascade: a group that holds servers cannot be deleted.
        ForeignKeyConstraint(["server_group_id"], ["server_groups.id"], name="servers_server_group_id_fkey"),
        CheckConstraint("port BETWEEN 1 AND 65535", name="servers_port_check"),
        CheckConstraint("os IN ('linux', 'windows')", name="servers_os_check"),
        CheckConstraint("(host_key IS NULL) = (host_key_pinned_at IS NULL)", name="servers_host_key_pinned_check"),
        CheckConstraint("host_key_changed_at IS NULL OR host_key IS NOT NULL", name="servers_host_key_changed_check"),
        # Names are unique across all groups, without regard to case.
        Index("servers_name_key", text("lower(name)"), unique=True),
        Index("servers_server_group_id_idx", "server_group_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    server_group_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(Text)
    address: Mapped[str] = mapped_column(Text)
    port: Mapped[int] = mapped_column(Integer)
    os: Mapped[str] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    # The pinned host key as an OpenSSH line ("ssh-ed25519 AAAA…"), set only by a pin.
    host_key: Mapped[str | None] = mapped_column(Text)
    host_key_pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The candidate: the key last fetched for pinning, or the key presented at a blocked connection.
    host_key_offered: Mapped[str | None] = mapped_column(Text)
    host_key_offered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when a connection met another key: the server is blocked until it is reviewed.
    host_key_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connection_settings: Mapped[dict] = mapped_column(JSONB, server_default=text("""'{"username": "megoo"}'::jsonb"""))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ServerTag(Base):
    __tablename__ = "server_tags"
    __table_args__ = (
        PrimaryKeyConstraint("server_id", "tag", name="server_tags_pkey"),
        ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE", name="server_tags_server_id_fkey"),
        CheckConstraint("tag = lower(tag) AND char_length(tag) BETWEEN 1 AND 32", name="server_tags_tag_check"),
        Index("server_tags_tag_idx", "tag"),
    )

    server_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    tag: Mapped[str] = mapped_column(Text)

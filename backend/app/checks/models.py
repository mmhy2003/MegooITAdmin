"""The last result of each slow check of a server, and the containers the collector found on it."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, get_args

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, PrimaryKeyConstraint, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

Kind = Literal["containers", "processes", "services", "logins", "updates", "certificates"]
KINDS: tuple[Kind, ...] = get_args(Kind)  # this order is the API's order
Status = Literal["ok", "not_available", "denied", "timeout", "failed"]
STATUSES: tuple[Status, ...] = get_args(Status)
CONTAINER_STATES = ("created", "running", "paused", "restarting", "removing", "exited", "dead", "unknown")


@dataclass(frozen=True)
class SeenContainer:
    container_id: str
    name: str
    image: str
    compose_project: str | None
    compose_service: str | None
    state: str
    status: str


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class ServerCheck(Base):
    """One row per server and check. data and data_at are the last successful result: a failed run keeps them."""

    __tablename__ = "server_checks"
    __table_args__ = (
        PrimaryKeyConstraint("server_id", "kind", name="server_checks_pkey"),
        ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE", name="server_checks_server_id_fkey"),
        CheckConstraint(f"kind IN ({_in(KINDS)})", name="server_checks_kind_check"),
        CheckConstraint(f"status IN ({_in(STATUSES)})", name="server_checks_status_check"),
        CheckConstraint("(data IS NULL) = (data_at IS NULL)", name="server_checks_data_check"),
    )

    server_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    data_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Container(Base):
    """A container the runtime listed at the last successful check. One it no longer lists is deleted then."""

    __tablename__ = "containers"
    __table_args__ = (
        PrimaryKeyConstraint("server_id", "runtime", "container_id", name="containers_pkey"),
        ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE", name="containers_server_id_fkey"),
        # Podman can join later without a schema change.
        CheckConstraint("runtime = 'docker'", name="containers_runtime_check"),
        CheckConstraint(f"state IN ({_in(CONTAINER_STATES)})", name="containers_state_check"),
    )

    server_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    runtime: Mapped[str] = mapped_column(Text)
    container_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    image: Mapped[str] = mapped_column(Text)
    compose_project: Mapped[str | None] = mapped_column(Text)
    compose_service: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    # Docker's own words, "Up 3 hours (healthy)".
    status: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

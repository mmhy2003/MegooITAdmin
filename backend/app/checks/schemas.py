"""The response bodies of /api/servers/{id}/checks and /api/servers/{id}/containers."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.checks.models import Kind

# A check's last status, or "not_checked" before its first run.
CheckState = Literal["ok", "not_available", "denied", "timeout", "failed", "not_checked"]


class CheckOut(BaseModel):
    kind: Kind
    status: CheckState
    checked_at: datetime | None
    every_seconds: int
    data: dict[str, Any] | None
    data_at: datetime | None


class ChecksOut(BaseModel):
    can_view_processes: bool
    checks: list[CheckOut]


class ContainerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    container_id: str
    runtime: str
    name: str
    image: str
    compose_project: str | None
    compose_service: str | None
    state: str
    status: str
    first_seen_at: datetime
    last_seen_at: datetime

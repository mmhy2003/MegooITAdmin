"""The request and response bodies of /api/servers, and the rules a server's fields follow."""

import ipaddress
import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.inventory.schemas import _none_if_empty

NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
TAG_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,31}$"
HOST_LABEL = r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
HOSTNAME_PATTERN = rf"^{HOST_LABEL}(\.{HOST_LABEL})*\.?$"
MAX_TAGS = 20
DEFAULT_USERNAME = "megoo"
Os = Literal["linux", "windows"]
HostKeyState = Literal["none", "not_pinned", "pinned", "changed"]
MonitoringState = Literal["reachable", "unreachable", "not_monitored"]


def clean_address(value: str) -> str:
    """An IPv4 or IPv6 address in its canonical text, or a host name of at most 253 characters; lowercase."""
    value = value.strip().lower()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    if not 1 <= len(value) <= 253 or not re.fullmatch(HOSTNAME_PATTERN, value):
        raise ValueError("not an IP address or a host name")
    return value


def clean_tags(values: list[str]) -> list[str]:
    """Trimmed, lowercased, deduplicated and sorted; each one matches TAG_PATTERN; at most MAX_TAGS."""
    tags = sorted({v.strip().lower() for v in values})
    for tag in tags:
        if not re.fullmatch(TAG_PATTERN, tag):
            raise ValueError(f"{tag!r} is not a tag")
    if len(tags) > MAX_TAGS:
        raise ValueError(f"at most {MAX_TAGS} tags")
    return tags


ServerName = Annotated[str, StringConstraints(strip_whitespace=True, pattern=NAME_PATTERN)]
Address = Annotated[str, AfterValidator(clean_address)]
Port = Annotated[int, Field(ge=1, le=65535)]
Role = Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)]
Tags = Annotated[list[str], AfterValidator(clean_tags)]
# Seconds between two samples of the collector.
MetricsInterval = Annotated[int, Field(ge=1, le=10)]
Username = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r"^\S+$")
]


class ConnectionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: Username = DEFAULT_USERNAME

    @field_validator("username")
    @classmethod
    def _not_root(cls, value: str) -> str:
        if value == "root":
            raise ValueError("the login account may not be root")
        return value


class ServerIn(BaseModel):
    name: ServerName
    address: Address
    group_id: UUID
    os: Os
    port: Port
    # An empty role is stored as none.
    role: Role | None = None
    tags: Tags = []
    connection_settings: ConnectionSettings = ConnectionSettings()
    metrics_interval_seconds: MetricsInterval = 5

    _role = field_validator("role")(_none_if_empty)


class ServerPatch(BaseModel):
    """Only the fields sent change (model_fields_set). Only role may be sent as null."""

    name: ServerName | None = None
    address: Address | None = None
    group_id: UUID | None = None
    os: Os | None = None
    port: Port | None = None
    role: Role | None = None
    tags: Tags | None = None
    connection_settings: ConnectionSettings | None = None
    metrics_interval_seconds: MetricsInterval | None = None

    _role = field_validator("role")(_none_if_empty)

    @field_validator("name", "address", "group_id", "os", "port", "tags", "connection_settings", "metrics_interval_seconds")
    @classmethod
    def _not_null(cls, value):
        if value is None:
            raise ValueError("may not be null")
        return value


class HostKeyOffer(BaseModel):
    fingerprint: str
    type: str
    at: datetime


class Monitoring(BaseModel):
    """What the collector last saw of the server."""

    state: MonitoringState
    reason: str | None
    since: datetime
    last_sample_at: datetime | None


class ServerOut(BaseModel):
    id: UUID
    name: str
    address: str
    port: int
    os: Os
    role: str | None
    tags: list[str]
    group_id: UUID
    group_name: str
    connection_settings: ConnectionSettings
    host_key: str | None
    host_key_state: HostKeyState
    host_key_fingerprint: str | None
    host_key_type: str | None
    host_key_pinned_at: datetime | None
    host_key_changed_at: datetime | None
    # Only in the state "changed", and only when the presented key could be read.
    host_key_offered: HostKeyOffer | None
    metrics_interval_seconds: int
    # None until the collector wrote a state for the server.
    monitoring: Monitoring | None
    created_at: datetime
    updated_at: datetime
    # Whether the person may edit, move and remove it.
    can_manage: bool
    # Whether the person may test the connection: a Linux server and Connect SSH in its group.
    can_connect: bool
    # Whether the person may follow its logs: a Linux server and View logs in its group.
    can_view_logs: bool

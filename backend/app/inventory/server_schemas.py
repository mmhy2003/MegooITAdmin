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
Username = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r"^\S+$")
]


class ConnectionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: Username = DEFAULT_USERNAME


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

    _role = field_validator("role")(_none_if_empty)

    @field_validator("name", "address", "group_id", "os", "port", "tags", "connection_settings")
    @classmethod
    def _not_null(cls, value):
        if value is None:
            raise ValueError("may not be null")
        return value


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
    created_at: datetime
    updated_at: datetime
    # Whether the person may edit, move and remove it.
    can_manage: bool

"""The request and response bodies of /api/server-groups."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, StringConstraints, field_validator

GroupName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


def _none_if_empty(value: str | None) -> str | None:
    return value or None


class ServerGroupIn(BaseModel):
    name: GroupName
    # An empty description is stored as none.
    description: Description | None = None

    _description = field_validator("description")(_none_if_empty)


class ServerGroupPatch(BaseModel):
    """Only the fields sent change (model_fields_set)."""

    name: GroupName | None = None
    description: Description | None = None

    _description = field_validator("description")(_none_if_empty)


class ServerGroupOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    created_at: datetime
    # How many people hold a role in the group: only an Owner is told.
    member_count: int | None

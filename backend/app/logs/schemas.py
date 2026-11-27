"""The request and response bodies of /api/server-groups/{group_id}/log-allowlist."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.logs.allowlist import check_pattern


class PatternIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: str

    # A pattern outside the rules of app.logs.allowlist answers 422.
    _pattern = field_validator("pattern")(check_pattern)


class PatternOut(BaseModel):
    id: UUID
    pattern: str
    created_at: datetime


class AllowlistOut(BaseModel):
    # Whether the person adds and removes patterns: the Owner, or an Admin of the group.
    can_manage: bool
    # By pattern.
    patterns: list[PatternOut]

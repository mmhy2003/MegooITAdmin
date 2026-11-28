"""The request and response bodies of /api/server-groups/{group_id}/log-allowlist and /api/log-views."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.logs.allowlist import check_pattern
from app.logs.sources import CONTAINER, ContainerSource, FileSource, JournalSource

LevelGroup = Literal["error", "warning", "info", "debug", "none"]
LEVEL_GROUPS: tuple[str, ...] = ("error", "warning", "info", "debug", "none")
MAX_VIEW_SOURCES = 16
MAX_VIEW_NAME = 80
MAX_FILTER = 200


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


class ContainerViewSource(ContainerSource):
    # The container's name when it was saved, so the view can show it before the server answers.
    name: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is not None and not CONTAINER.fullmatch(value):
            raise ValueError("not a container")
        return value


class ViewSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: str = Field("", max_length=MAX_FILTER)
    # The regex is not compiled here: the browser's engine differs.
    regex: bool = False
    levels: list[LevelGroup] = list(LEVEL_GROUPS)
    layout: Literal["side_by_side", "merged"] = "side_by_side"
    wrap: bool = False
    utc: bool = False

    @field_validator("levels")
    @classmethod
    def _levels(cls, value: list[str]) -> list[str]:
        """Each level once, in LEVEL_GROUPS order."""
        return [level for level in LEVEL_GROUPS if level in value]


ViewSource = Annotated[JournalSource | FileSource | ContainerViewSource, Field(discriminator="kind")]


class LogViewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    shared: bool = False
    sources: list[ViewSource] = Field(min_length=1, max_length=MAX_VIEW_SOURCES)
    settings: ViewSettings = ViewSettings()

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        """The name without surrounding blanks; empty or over MAX_VIEW_NAME characters answers 422."""
        value = value.strip()
        if not 1 <= len(value) <= MAX_VIEW_NAME:
            raise ValueError(f"a name of 1 to {MAX_VIEW_NAME} characters")
        return value


class LogViewOut(BaseModel):
    id: UUID
    name: str
    shared: bool
    # The name of the person who saved it.
    owner_name: str
    is_mine: bool
    # Whether the person replaces and deletes it: the one who saved it, or the Owner.
    can_edit: bool
    sources: list[ViewSource]
    settings: ViewSettings
    updated_at: datetime

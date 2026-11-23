"""The request and response bodies of /api/users and of the invite routes under /api/auth."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.access.permissions import ALLOWED, GroupRole, Permission, PlatformRole
from app.auth.passwords import PASSWORD_MAX, PASSWORD_MIN

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Email = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=254, pattern=r"^[^@\s]+@[^@\s]+$")
]


class GrantIn(BaseModel):
    """A person's role in one server group and its seven switches."""

    group_id: UUID
    role: GroupRole
    connect_ssh: bool = False
    connect_rdp: bool = False
    view_logs: bool = False
    view_processes: bool = False
    manage_processes: bool = False
    run_playbooks: bool = False
    manage_playbooks: bool = False

    @model_validator(mode="after")
    def _only_allowed_switches(self) -> Self:
        refused = [p.value for p in Permission if getattr(self, p.value) and p not in ALLOWED[self.role]]
        if refused:
            raise ValueError(f"the role {self.role} cannot hold {', '.join(refused)}")
        return self

    def fields(self) -> dict[str, str | bool]:
        """The role and the seven switches, as RoleGrant.fields() gives them."""
        return {"role": self.role.value, **{p.value: getattr(self, p.value) for p in Permission}}


class GrantOut(GrantIn):
    group_name: str


class AccessIn(BaseModel):
    """The whole access of a person: a platform role, or roles per server group, or nothing."""

    platform_role: PlatformRole | None = None
    grants: list[GrantIn] = []

    @model_validator(mode="after")
    def _one_kind_of_access(self) -> Self:
        group_ids = [g.group_id for g in self.grants]
        if len(set(group_ids)) != len(group_ids):
            raise ValueError("a server group is listed twice")
        if self.platform_role is not None and self.grants:
            raise ValueError("an Owner or an Auditor holds no group roles")
        return self


class InviteIn(AccessIn):
    name: Name
    email: Email


class UserRowOut(BaseModel):
    id: UUID
    name: str
    email: str
    platform_role: PlatformRole | None
    status: Literal["active", "invited", "disabled"]
    mfa_enrolled: bool
    invite_expires_at: datetime | None
    grants: list[GrantOut]  # by group name


class InviteLinkOut(BaseModel):
    """The only answer that ever holds the token."""

    user_id: UUID
    token: str
    expires_at: datetime


class InviteTokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=128)


class InviteAcceptIn(InviteTokenIn):
    password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)


class InviteInfoOut(BaseModel):
    name: str
    email: str

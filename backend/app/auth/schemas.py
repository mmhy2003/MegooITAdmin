"""The request and response bodies of /api/auth."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.auth.service import Status


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str
    is_owner: bool


class SessionStatusOut(BaseModel):
    status: Status
    user: UserOut | None  # only when the status is active


class StatusOut(BaseModel):
    status: Status

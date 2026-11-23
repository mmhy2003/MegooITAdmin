"""The request and response bodies of /api/auth."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.auth.passwords import PASSWORD_MAX, PASSWORD_MIN
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


class SetupIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)


class LoginIn(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


Method = Literal["totp", "recovery_code"]


class CodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    method: Method = "totp"


class EnrolIn(BaseModel):
    code: str | None = Field(default=None, max_length=64)  # a current code; needed to replace an authenticator
    method: Method = "totp"


class EnrolOut(BaseModel):
    secret: str
    uri: str


class ConfirmIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class ConfirmOut(BaseModel):
    recovery_codes: list[str] | None  # only at the first enrolment

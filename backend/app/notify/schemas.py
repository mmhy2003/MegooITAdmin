"""The request and response bodies of /api/notifications/email."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, BeforeValidator, Field, StringConstraints, model_validator

from app.users.schemas import Email

Severity = Literal["warning", "critical"]
MAX_EXTRA_ADDRESSES = 20


def _blank_is_none(value: object) -> object:
    """A blank text is no value: the pages send "" for an empty field."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _unique(addresses: list[str]) -> list[str]:
    """The addresses once each, in the order sent, and at most MAX_EXTRA_ADDRESSES of them."""
    unique = list(dict.fromkeys(addresses))
    if len(unique) > MAX_EXTRA_ADDRESSES:
        raise ValueError(f"at most {MAX_EXTRA_ADDRESSES} addresses")
    return unique


Text = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None, BeforeValidator(_blank_is_none)
]
Address = Annotated[Email | None, BeforeValidator(_blank_is_none)]


class EmailIn(BaseModel):
    """The whole email settings. password omitted or None keeps the saved one, "" removes it, and any other text
    replaces it."""

    enabled: bool
    host: Text = None
    port: Annotated[int, Field(ge=1, le=65535)] = 587
    security: Literal["starttls", "tls", "none"] = "starttls"
    username: Text = None
    password: Annotated[str | None, Field(max_length=1024)] = None
    from_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] = "MegooITAdmin"
    from_address: Address = None
    extra_addresses: Annotated[list[Email], AfterValidator(_unique)] = []
    min_severity: Severity = "warning"

    @model_validator(mode="after")
    def _ready_when_enabled(self) -> Self:
        if self.enabled and (self.host is None or self.from_address is None):
            raise ValueError("email needs a host and a from address before it is switched on")
        return self


class DeliveryOut(BaseModel):
    """The last delivery: at is when it was delivered, when it is tried next while pending, or when it was last tried
    once it failed."""

    state: Literal["pending", "delivered", "failed"]
    at: datetime
    error: str | None


class EmailOut(BaseModel):
    enabled: bool
    host: str | None
    port: int
    security: str
    username: str | None
    password_set: bool
    from_name: str
    from_address: str | None
    extra_addresses: list[str]
    min_severity: str
    last_delivery: DeliveryOut | None


class TestResultOut(BaseModel):
    ok: bool
    error: str | None

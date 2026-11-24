"""The request and response bodies of a server's host key and connection test, and of the platform's public key."""

from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints, field_validator

from app.inventory.schemas import _none_if_empty

# Why a fetch or a test failed: a fixed set, never what the other side sent.
Reason = Literal[
    "unreachable",
    "host_key_changed",
    "key_refused",
    "account_is_root",
    "account_in_docker_group",
    "account_not_in_log_groups",
    "sudo_checker_missing",
    "sudo_too_wide",
    "account_check_failed",
    "ssh_error",
]
CheckName = Literal[
    "host_key", "platform_key", "not_root", "not_in_docker_group", "in_log_groups", "sudo_checker", "sudo_limited"
]
CheckStatus = Literal["passed", "failed", "not_run"]


class Check(BaseModel):
    name: CheckName
    status: CheckStatus


class ConnectionTestResult(BaseModel):
    ok: bool
    reason: Reason | None
    # Always the seven, in CheckName order.
    checks: list[Check]


class HostKeyFetchResult(BaseModel):
    ok: bool
    reason: Reason | None
    fingerprint: str | None
    type: str | None


class HostKeyPin(BaseModel):
    """The fingerprint the admin compared: the backend pins its candidate only when it is that key."""

    fingerprint: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    # Needed only to accept a changed key. Empty is none.
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None

    _reason = field_validator("reason")(_none_if_empty)


class PublicKeyOut(BaseModel):
    public_key: str

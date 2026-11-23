"""What an audit event holds, validated before anything touches the database."""

import ipaddress
from collections.abc import Collection, Mapping
from enum import StrEnum
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

ACTION_PATTERN = r"^[a-z0-9_]+(\.[a-z0-9_]+)+$"
USER_AGENT_MAX = 1024
REDACTED = "[redacted]"
# A field whose name contains one of these is a secret, whether or not the caller names it.
SECRET_HINTS = ("password", "secret", "token")


def check_json(value: Any) -> Any:
    """Returns the value unchanged when it is JSON without floats. A float is refused because PostgreSQL may write
    it back differently, which would change the event's hash."""
    if value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, list):
        for item in value:
            check_json(item)
        return value
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            check_json(item)
        return value
    raise ValueError("audit values must be JSON without floats")


Json = Annotated[dict[str, Any], AfterValidator(check_json)]


class ActorType(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


class Result(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    ERROR = "error"


class RiskClass(StrEnum):
    PLATFORM_READ = "platform_read"
    SERVER_READ = "server_read"
    CHANGE = "change"
    DESTRUCTIVE = "destructive"
    FORBIDDEN = "forbidden"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Actor(_Frozen):
    type: ActorType
    id: str | None = None
    name: str = Field(min_length=1)
    details: Json = {}

    @classmethod
    def human(cls, id: object, name: str) -> "Actor":
        return cls(type=ActorType.HUMAN, id=str(id), name=name)

    @classmethod
    def agent(cls, session_id: object, profile: str, model: str) -> "Actor":
        session = str(session_id)
        return cls(
            type=ActorType.AGENT,
            id=session,
            name=profile,
            details={"session": session, "profile": profile, "model": model},
        )

    @classmethod
    def system(cls, component: str) -> "Actor":
        return cls(type=ActorType.SYSTEM, name=component)


class Person(_Frozen):
    """The person an agent or a scheduled job acts for."""

    id: str
    name: str


class Target(_Frozen):
    type: str = Field(min_length=1)
    id: str | None = None
    name: str | None = None


class Source(_Frozen):
    ip: str | None = None
    user_agent: str | None = None
    auth_method: str | None = None
    mfa: bool | None = None

    @field_validator("ip")
    @classmethod
    def _one_text_form(cls, value: str | None) -> str | None:
        return None if value is None else str(ipaddress.ip_address(value))

    @field_validator("user_agent")
    @classmethod
    def _cut(cls, value: str | None) -> str | None:
        return None if value is None else value[:USER_AGENT_MAX]


class Event(_Frozen):
    action: str = Field(pattern=ACTION_PATTERN)
    actor: Actor
    result: Result = Result.SUCCESS
    target: Target | None = None
    on_behalf_of: Person | None = None
    context: dict[str, str] = {}
    source: Source | None = None
    reason: str | None = None
    change: Json | None = None
    result_detail: Json | None = None
    risk_class: RiskClass | None = None

    def columns(self) -> dict[str, Any]:
        """The event as the values of its audit_log columns: enums as their text, an absent object as None."""
        target, person, source = self.target, self.on_behalf_of, self.source
        return {
            "actor_type": self.actor.type.value,
            "actor_id": self.actor.id,
            "actor_name": self.actor.name,
            "actor_details": self.actor.details,
            "on_behalf_of_id": person.id if person else None,
            "on_behalf_of_name": person.name if person else None,
            "action": self.action,
            "target_type": target.type if target else None,
            "target_id": target.id if target else None,
            "target_name": target.name if target else None,
            "context": self.context,
            "source_ip": source.ip if source else None,
            "user_agent": source.user_agent if source else None,
            "auth_method": source.auth_method if source else None,
            "mfa": source.mfa if source else None,
            "reason": self.reason,
            "change": self.change,
            "result": self.result.value,
            "result_detail": self.result_detail,
            "risk_class": self.risk_class.value if self.risk_class else None,
        }


def changes(
    before: Mapping[str, Any], after: Mapping[str, Any], *, secret: Collection[str] = ()
) -> dict[str, Any] | None:
    """The fields that differ, as {"field": {"before": ..., "after": ...}}, with the values of secret fields
    replaced by REDACTED. None when nothing differs."""
    diff = {}
    for key in sorted(before.keys() | after.keys()):
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        if key in secret or any(hint in key.lower() for hint in SECRET_HINTS):
            old = new = REDACTED
        diff[key] = {"before": old, "after": new}
    return diff or None

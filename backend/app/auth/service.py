"""The auth flows, between the routes and the tables."""

import hmac
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from fastapi import HTTPException, Request
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import Actor, ActorType, Event, Result, Target, record, source_of
from app.auth import actions, clock
from app.auth.models import SetupCode, User
from app.auth.passwords import hash_password
from app.auth.recovery import hash_code
from app.auth.sessions import create_session, lookup_session

if TYPE_CHECKING:
    from app.auth.schemas import SetupIn

MAX_FAILURES = 5
ACTOR_NAME_MAX = 254

Status = Literal["setup_required", "signed_out", "mfa_required", "enrolment_required", "active"]


@dataclass(frozen=True)
class Refusal:
    """A refused request whose event is recorded, so the route answers it without raising and the event commits."""

    status: int
    reason: str


def actor_of(user: User) -> Actor:
    return Actor.human(user.id, user.name)


def target_of(user: User) -> Target:
    return Target(type="user", id=str(user.id), name=user.email)


def auth_event(
    request: Request,
    action: str,
    actor: Actor,
    *,
    mfa: bool,
    target: Target | None = None,
    result: Result = Result.SUCCESS,
    detail: dict | None = None,
) -> Event:
    return Event(
        action=action,
        actor=actor,
        target=target,
        result=result,
        result_detail=detail,
        source=source_of(request, auth_method="password", mfa=mfa),
    )


def _typed_actor(email: str) -> Actor:
    """The actor of an attempt that matched no account: the email as typed, without an ID."""
    return Actor(type=ActorType.HUMAN, name=email.strip()[:ACTOR_NAME_MAX] or "unknown")


async def _any_user(db: AsyncSession) -> bool:
    return bool(await db.scalar(select(exists().select_from(User))))


async def status_of(db: AsyncSession, token: str | None) -> tuple[Status, User | None]:
    """Where the browser with this token stands. The user is returned only for an active session."""
    if not await _any_user(db):
        return "setup_required", None
    session = (await lookup_session(db, token)).session
    if session is None:
        return "signed_out", None
    if session.stage == "active":
        return "active", session.user
    return ("mfa_required" if session.user.totp_secret is not None else "enrolment_required"), None


async def setup(db: AsyncSession, request: Request, body: "SetupIn") -> tuple[User, str] | Refusal:
    """Creates the Owner with the one-time setup code, and a pending session that goes on to enrolment."""
    # The row lock makes concurrent setups wait; the one that comes second finds the row gone and an owner.
    row = await db.scalar(select(SetupCode).where(SetupCode.id == 1).with_for_update())
    if row is None:
        if await _any_user(db):
            raise HTTPException(409, "setup_closed")
        await record(
            db,
            auth_event(
                request,
                actions.SETUP_FAILED,
                _typed_actor(body.email),
                mfa=False,
                result=Result.FAILURE,
                detail={"reason": actions.NO_CODE},
            ),
        )
        return Refusal(401, "no_setup_code")

    if not hmac.compare_digest(hash_code(body.code), row.code_hash):
        row.failed_attempts += 1
        reason = "wrong_setup_code"
        if row.failed_attempts >= MAX_FAILURES:
            await db.delete(row)
            reason = "no_setup_code"
        await db.flush()
        await record(
            db,
            auth_event(
                request,
                actions.SETUP_FAILED,
                _typed_actor(body.email),
                mfa=False,
                result=Result.FAILURE,
                detail={"reason": actions.WRONG_CODE},
            ),
        )
        return Refusal(401, reason)

    user = User(
        email=body.email.strip().lower(),
        name=body.name.strip(),
        password_hash=await hash_password(body.password),
        is_owner=True,
        password_changed_at=clock.now(),
    )
    db.add(user)
    await db.flush()
    await db.delete(row)
    token = await create_session(db, user, source_of(request), stage="pending")
    await record(db, auth_event(request, actions.OWNER_CREATED, actor_of(user), target=target_of(user), mfa=False))
    return user, token

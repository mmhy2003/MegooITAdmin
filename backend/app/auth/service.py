"""The auth flows, between the routes and the tables."""

import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import Actor, ActorType, Event, Result, Target, record, source_of
from app.auth import actions, clock, passwords
from app.auth.models import SetupCode, User
from app.auth.passwords import hash_password
from app.auth.recovery import hash_code
from app.auth.sessions import create_session, delete_expired, lookup_session

if TYPE_CHECKING:
    from app.auth.schemas import LoginIn, SetupIn

MAX_FAILURES = 5
LOCK_TIME = timedelta(minutes=15)
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


async def lock_user(db: AsyncSession, user_id: UUID) -> User:
    """The user's row, locked until the commit, so parallel attempts cannot pass the failure counter."""
    query = select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)
    return (await db.scalars(query)).one()


def is_locked(user: User, now: datetime) -> bool:
    return user.locked_until is not None and user.locked_until > now


def register_failure(user: User, now: datetime) -> bool:
    """Counts a wrong password or code. Returns True when this one locks the account."""
    if user.locked_until is not None and user.locked_until <= now:
        # The lock is over: the count starts again.
        user.locked_until = None
        user.failed_attempts = 0
    user.failed_attempts += 1
    if user.failed_attempts >= MAX_FAILURES:
        user.locked_until = now + LOCK_TIME
        user.failed_attempts = 0
        return True
    return False


def register_success(user: User) -> None:
    user.failed_attempts = 0
    user.locked_until = None


async def fail_attempt(
    db: AsyncSession,
    request: Request,
    user: User,
    *,
    action: str,
    reason: str,
    mfa: bool,
    method: str | None = None,
) -> bool:
    """Counts the failure and records it, and the lock when it locks. Returns True when the account is now locked."""
    locked = register_failure(user, clock.now())
    await db.flush()
    detail = {"reason": reason} if method is None else {"reason": reason, "method": method}
    await record(
        db,
        auth_event(
            request, action, actor_of(user), target=target_of(user), mfa=mfa, result=Result.FAILURE, detail=detail
        ),
    )
    if locked:
        await record(
            db, auth_event(request, actions.ACCOUNT_LOCKED, actor_of(user), target=target_of(user), mfa=mfa)
        )
    return locked


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


async def login(db: AsyncSession, request: Request, body: "LoginIn") -> tuple[str, Status] | Refusal:
    """The password step. A right password gives a pending session; the second factor comes next."""
    email = body.email.strip().lower()
    # The row lock serialises parallel guesses at one account, so none slips past the counter.
    user = await db.scalar(select(User).where(User.email == email).with_for_update())
    # Every refusal answers the same, so the page never says whether an account exists or is locked.
    refusal = Refusal(401, "invalid_credentials")
    if user is None:
        # As slow as a real check, so the time does not tell either.
        await passwords.verify_dummy(body.password)
        await record(
            db,
            auth_event(
                request,
                actions.SIGN_IN_FAILED,
                _typed_actor(body.email),
                mfa=False,
                result=Result.FAILURE,
                detail={"reason": actions.UNKNOWN_ACCOUNT},
            ),
        )
        return refusal

    if is_locked(user, clock.now()):
        # The password is not checked, so the lock gives no hint about it.
        await record(
            db,
            auth_event(
                request,
                actions.SIGN_IN_FAILED,
                actor_of(user),
                target=target_of(user),
                mfa=False,
                result=Result.FAILURE,
                detail={"reason": actions.LOCKED},
            ),
        )
        return refusal

    if not await passwords.verify_password(user.password_hash, body.password):
        await fail_attempt(db, request, user, action=actions.SIGN_IN_FAILED, reason=actions.WRONG_PASSWORD, mfa=False)
        return refusal

    # The counter is not reset here: a password alone must not buy endless guesses at the code.
    if passwords.needs_rehash(user.password_hash):
        user.password_hash = await hash_password(body.password)
    await delete_expired(db, user.id)
    token = await create_session(db, user, source_of(request), stage="pending")
    await record(db, auth_event(request, actions.PASSWORD_ACCEPTED, actor_of(user), target=target_of(user), mfa=False))
    return token, ("mfa_required" if user.totp_secret is not None else "enrolment_required")

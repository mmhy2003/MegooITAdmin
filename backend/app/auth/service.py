"""The auth flows, between the routes and the tables."""

import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import Actor, ActorType, Event, Result, Target, record, source_of
from app.auth import actions, clock, passwords, recovery, totp
from app.auth.crypto import SecretUndecryptable, decrypt_secret, encrypt_secret
from app.auth.models import AuthSession, RecoveryCode, SetupCode, User
from app.auth.passwords import hash_password
from app.auth.recovery import hash_code
from app.auth.sessions import create_session, delete_expired, end_sessions, is_expired, lookup_session
from app.core.config import get_settings

if TYPE_CHECKING:
    from app.auth.schemas import (
        CodeIn,
        ConfirmIn,
        EnrolIn,
        EnrolOut,
        LoginIn,
        MeOut,
        PasswordIn,
        RecoveryCodesIn,
        SessionOut,
        SetupIn,
    )

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
    change: dict | None = None,
    context: dict[str, str] | None = None,
) -> Event:
    return Event(
        action=action,
        actor=actor,
        target=target,
        result=result,
        result_detail=detail,
        change=change,
        context=context or {},
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


async def check_second_factor(db: AsyncSession, user: User, code: str, method: str, now: datetime) -> str | None:
    """None when the code is accepted, else the reason: WRONG_CODE or UNDECRYPTABLE. A used code cannot come again."""
    if method == "totp":
        try:
            secret = decrypt_secret(get_settings().auth_key(), user.id, user.totp_secret)
        except SecretUndecryptable:
            return actions.UNDECRYPTABLE
        step = totp.verify(secret, code, user.totp_last_step, now)
        if step is None:
            return actions.WRONG_CODE
        user.totp_last_step = step
        return None
    used = await db.scalar(
        delete(RecoveryCode)
        .where(RecoveryCode.user_id == user.id, RecoveryCode.code_hash == hash_code(code))
        .returning(RecoveryCode.id)
    )
    return None if used is not None else actions.WRONG_CODE


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


async def reset_second_factor(db: AsyncSession, user: User) -> list[AuthSession]:
    """Removes the account's authenticator and recovery codes and ends its sessions, so the next sign-in enrols.
    Records nothing: the caller records who reset it."""
    user.totp_secret = None
    user.totp_pending_secret = None
    user.totp_confirmed_at = None
    user.totp_last_step = None
    await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    return await end_sessions(db, user.id)


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
        platform_role="owner",
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

    # No password opens a disabled or a not-yet-accepted account, so the attempt is not counted.
    closed = None
    if user.disabled_at is not None:
        closed = actions.DISABLED
    elif user.password_hash is None:
        closed = actions.NOT_ACCEPTED
    if closed is not None:
        await passwords.verify_dummy(body.password)
        await record(
            db,
            auth_event(
                request,
                actions.SIGN_IN_FAILED,
                actor_of(user),
                target=target_of(user),
                mfa=False,
                result=Result.FAILURE,
                detail={"reason": closed},
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


async def verify_second_factor(
    db: AsyncSession, request: Request, session: AuthSession, body: "CodeIn"
) -> str | Refusal:
    """The code step. A right TOTP or recovery code replaces the pending session with an active one, under a new
    token, which is returned."""
    if session.stage == "active":
        raise HTTPException(409, "already_signed_in")
    user = await lock_user(db, session.user_id)
    if user.totp_secret is None:
        raise HTTPException(409, "not_enrolled")
    method = body.method

    if is_locked(user, clock.now()):
        await record(
            db,
            auth_event(
                request,
                actions.MFA_FAILED,
                actor_of(user),
                target=target_of(user),
                mfa=False,
                result=Result.FAILURE,
                detail={"reason": actions.LOCKED, "method": method},
            ),
        )
        return Refusal(401, "locked")

    reason = await check_second_factor(db, user, body.code, method, clock.now())
    if reason == actions.UNDECRYPTABLE:
        # Not counted: the code may be right, the key is what changed.
        await record(
            db,
            auth_event(
                request,
                actions.MFA_FAILED,
                actor_of(user),
                target=target_of(user),
                mfa=False,
                result=Result.FAILURE,
                detail={"reason": reason, "method": method},
            ),
        )
        return Refusal(401, "undecryptable")
    if reason is not None:
        locked = await fail_attempt(
            db, request, user, action=actions.MFA_FAILED, reason=reason, mfa=False, method=method
        )
        return Refusal(401, "locked" if locked else "wrong_code")

    register_success(user)
    await db.delete(session)
    await db.flush()
    token = await create_session(db, user, source_of(request), stage="active", mfa_method=method)
    await record(
        db,
        auth_event(
            request, actions.MFA_USED, actor_of(user), target=target_of(user), mfa=True, detail={"method": method}
        ),
    )
    await record(db, auth_event(request, actions.SIGN_IN, actor_of(user), target=target_of(user), mfa=True))
    return token


async def _record_mfa_failed(
    db: AsyncSession, request: Request, user: User, *, reason: str, mfa: bool, method: str | None = None
) -> None:
    """Records a refused second factor that is not counted: a lock already in place, or a secret that no longer
    decrypts."""
    detail = {"reason": reason} if method is None else {"reason": reason, "method": method}
    await record(
        db,
        auth_event(
            request,
            actions.MFA_FAILED,
            actor_of(user),
            target=target_of(user),
            mfa=mfa,
            result=Result.FAILURE,
            detail=detail,
        ),
    )


async def start_enrolment(
    db: AsyncSession, request: Request, session: AuthSession, body: "EnrolIn"
) -> "EnrolOut | Refusal":
    """Stores a new secret as the pending one, until a code from it confirms it. A pending session may do this only
    for an account without an authenticator. An active one replaces its authenticator, and proves itself first
    with a current code or a recovery code."""
    from app.auth.schemas import EnrolOut

    user = await lock_user(db, session.user_id)
    active = session.stage == "active"
    if not active:
        if user.totp_secret is not None:
            raise HTTPException(409, "already_enrolled")
    else:
        if body.code is None:
            raise HTTPException(422, "code_required")
        method = body.method
        if is_locked(user, clock.now()):
            await _record_mfa_failed(db, request, user, reason=actions.LOCKED, mfa=True, method=method)
            return Refusal(401, "locked")
        reason = await check_second_factor(db, user, body.code, method, clock.now())
        if reason == actions.UNDECRYPTABLE:
            # Not counted: the code may be right, the key is what changed.
            await _record_mfa_failed(db, request, user, reason=reason, mfa=True, method=method)
            return Refusal(401, "undecryptable")
        if reason is not None:
            locked = await fail_attempt(
                db, request, user, action=actions.MFA_FAILED, reason=reason, mfa=True, method=method
            )
            return Refusal(401, "locked" if locked else "wrong_code")
        register_success(user)

    secret = totp.new_secret()
    user.totp_pending_secret = encrypt_secret(get_settings().auth_key(), user.id, secret)
    await db.flush()
    await record(
        db, auth_event(request, actions.MFA_ENROLMENT_STARTED, actor_of(user), target=target_of(user), mfa=active)
    )
    return EnrolOut(secret=secret, uri=totp.provisioning_uri(secret, user.email))


async def confirm_enrolment(
    db: AsyncSession, request: Request, session: AuthSession, body: "ConfirmIn"
) -> tuple[list[str] | None, str | None] | Refusal:
    """A code from the pending secret makes it the authenticator. The first enrolment returns 10 recovery codes and
    the token of a new active session. A replacement ends the person's other sessions and returns (None, None)."""
    user = await lock_user(db, session.user_id)
    if user.totp_pending_secret is None:
        raise HTTPException(409, "no_enrolment")
    active = session.stage == "active"
    if not active and user.totp_secret is not None:
        # The same rule as `start_enrolment`: a replacement started elsewhere is not this session's to confirm.
        raise HTTPException(409, "already_enrolled")
    now = clock.now()
    if is_locked(user, now):
        await _record_mfa_failed(db, request, user, reason=actions.LOCKED, mfa=active)
        return Refusal(401, "locked")

    pending = decrypt_secret(get_settings().auth_key(), user.id, user.totp_pending_secret)
    step = totp.verify(pending, body.code, None, now)
    if step is None:
        locked = await fail_attempt(db, request, user, action=actions.MFA_FAILED, reason=actions.WRONG_CODE, mfa=active)
        return Refusal(401, "locked" if locked else "wrong_code")

    user.totp_secret = user.totp_pending_secret
    user.totp_pending_secret = None
    user.totp_confirmed_at = now
    user.totp_last_step = step
    register_success(user)

    if not active:
        await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
        codes = [recovery.new_code() for _ in range(recovery.RECOVERY_CODE_COUNT)]
        db.add_all(RecoveryCode(user_id=user.id, code_hash=hash_code(code)) for code in codes)
        await db.delete(session)
        await db.flush()
        token = await create_session(db, user, source_of(request), stage="active", mfa_method="totp")
        await record(db, auth_event(request, actions.MFA_ENROLLED, actor_of(user), target=target_of(user), mfa=True))
        await record(db, auth_event(request, actions.SIGN_IN, actor_of(user), target=target_of(user), mfa=True))
        return codes, token

    # Whoever held the old authenticator may hold the other sessions too.
    ended = await end_sessions(db, user.id, keep=session.id)
    await record(db, auth_event(request, actions.MFA_ENROLLED, actor_of(user), target=target_of(user), mfa=True))
    for other in ended:
        await record(
            db,
            auth_event(
                request,
                actions.SESSION_REVOKED,
                actor_of(user),
                target=Target(type="auth_session", id=str(other.id)),
                mfa=True,
            ),
        )
    return None, None


async def logout(db: AsyncSession, request: Request, session: AuthSession) -> None:
    """Ends this browser's session, pending or active."""
    user = session.user
    await db.delete(session)
    await db.flush()
    await record(
        db,
        auth_event(
            request, actions.SIGN_OUT, actor_of(user), target=target_of(user), mfa=session.stage == "active"
        ),
    )


async def me(db: AsyncSession, user: User) -> "MeOut":
    from app.auth.schemas import MeOut, UserOut

    left = await db.scalar(select(func.count()).select_from(RecoveryCode).where(RecoveryCode.user_id == user.id))
    return MeOut(
        user=UserOut.model_validate(user),
        password_changed_at=user.password_changed_at,
        totp_confirmed_at=user.totp_confirmed_at,
        recovery_codes_left=left,
    )


async def list_sessions(db: AsyncSession, session: AuthSession, user: User) -> "list[SessionOut]":
    """The person's signed-in sessions, newest first. Expired rows are left out, not deleted: this only reads."""
    from app.auth.schemas import SessionOut

    query = (
        select(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.stage == "active")
        .order_by(AuthSession.created_at.desc())
    )
    now = clock.now()
    return [
        SessionOut(
            id=s.id,
            current=s.id == session.id,
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
            ip=str(s.ip) if s.ip is not None else None,
            user_agent=s.user_agent,
            mfa_method=s.mfa_method,
        )
        for s in (await db.scalars(query)).all()
        if not is_expired(s, now)
    ]


async def revoke_session(
    db: AsyncSession, request: Request, session: AuthSession, user: User, session_id: UUID
) -> None:
    """Ends another of the person's sessions. This one ends with sign-out instead."""
    if session_id == session.id:
        raise HTTPException(409, "current_session")
    other = await db.scalar(select(AuthSession).where(AuthSession.id == session_id, AuthSession.user_id == user.id))
    if other is None:
        # Someone else's session answers the same as none, so IDs cannot be probed.
        raise HTTPException(404, "not_found")
    await db.delete(other)
    await db.flush()
    await record(
        db,
        auth_event(
            request,
            actions.SESSION_REVOKED,
            actor_of(user),
            target=Target(type="auth_session", id=str(session_id)),
            mfa=True,
        ),
    )


async def change_password(
    db: AsyncSession, request: Request, session: AuthSession, user: User, body: "PasswordIn"
) -> Refusal | None:
    """Sets a new password, proven with the current one, and ends the person's other sessions."""
    user = await lock_user(db, user.id)
    now = clock.now()
    if is_locked(user, now):
        await record(
            db,
            auth_event(
                request,
                actions.PASSWORD_CHANGED,
                actor_of(user),
                target=target_of(user),
                mfa=True,
                result=Result.FAILURE,
                detail={"reason": actions.LOCKED},
            ),
        )
        return Refusal(401, "locked")

    if not await passwords.verify_password(user.password_hash, body.current_password):
        locked = await fail_attempt(
            db, request, user, action=actions.PASSWORD_CHANGED, reason=actions.WRONG_PASSWORD, mfa=True
        )
        return Refusal(401, "locked" if locked else "wrong_password")

    user.password_hash = await hash_password(body.new_password)
    user.password_changed_at = now
    register_success(user)
    # Whoever knew the old password may hold the other sessions.
    ended = await end_sessions(db, user.id, keep=session.id)
    await record(db, auth_event(request, actions.PASSWORD_CHANGED, actor_of(user), target=target_of(user), mfa=True))
    for other in ended:
        await record(
            db,
            auth_event(
                request,
                actions.SESSION_REVOKED,
                actor_of(user),
                target=Target(type="auth_session", id=str(other.id)),
                mfa=True,
            ),
        )
    return None


async def new_recovery_codes(
    db: AsyncSession, request: Request, user: User, body: "RecoveryCodesIn"
) -> list[str] | Refusal:
    """Replaces the person's recovery codes with 10 new ones, proven with a current TOTP code."""
    user = await lock_user(db, user.id)
    now = clock.now()
    if is_locked(user, now):
        await _record_mfa_failed(db, request, user, reason=actions.LOCKED, mfa=True, method="totp")
        return Refusal(401, "locked")

    reason = await check_second_factor(db, user, body.code, "totp", now)
    if reason == actions.UNDECRYPTABLE:
        # Not counted: the code may be right, the key is what changed.
        await _record_mfa_failed(db, request, user, reason=reason, mfa=True, method="totp")
        return Refusal(401, "undecryptable")
    if reason is not None:
        locked = await fail_attempt(
            db, request, user, action=actions.MFA_FAILED, reason=reason, mfa=True, method="totp"
        )
        return Refusal(401, "locked" if locked else "wrong_code")

    register_success(user)
    await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes = [recovery.new_code() for _ in range(recovery.RECOVERY_CODE_COUNT)]
    db.add_all(RecoveryCode(user_id=user.id, code_hash=hash_code(code)) for code in codes)
    await db.flush()
    await record(
        db,
        auth_event(
            request,
            actions.RECOVERY_CODES_CREATED,
            actor_of(user),
            target=target_of(user),
            mfa=True,
            detail={"count": len(codes)},
        ),
    )
    return codes

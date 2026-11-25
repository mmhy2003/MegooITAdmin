"""Sessions: a row per signed-in browser, keyed by the SHA-256 of a random token that only the cookie holds.

A pending session (password right, second factor to come) lives 10 minutes. An active one ends after
session_idle_minutes without a request (background requests do not count) and session_absolute_minutes after
sign-in. Revoking a session deletes its row.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import Request, Response
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.audit import Source
from app.auth import clock
from app.auth.models import AuthSession, User
from app.core.config import get_settings

COOKIE = "megoo_session"
PENDING_LIFETIME = timedelta(minutes=10)
# last_seen_at is written at most this often, so most requests do not write.
TOUCH_EVERY = timedelta(minutes=1)
# A request with this header set to 1 (the pages' automatic re-reads) does not move last_seen_at: it can only let a
# session end sooner, never keep it alive.
BACKGROUND_HEADER = "x-megoo-background"


@dataclass(frozen=True)
class Lookup:
    session: AuthSession | None  # valid, with .user loaded
    expired: AuthSession | None  # presented but past a limit; already deleted and flushed


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def _idle_limit() -> timedelta:
    return timedelta(minutes=get_settings().session_idle_minutes)


def is_expired(session: AuthSession, now: datetime) -> bool:
    return now >= session.expires_at or now - session.last_seen_at >= _idle_limit()


async def create_session(
    db: AsyncSession,
    user: User,
    source: Source,
    *,
    stage: Literal["pending", "active"],
    mfa_method: str | None = None,
) -> str:
    """Adds a session for the user and returns its token. Only the token's hash is stored."""
    now = clock.now()
    lifetime = PENDING_LIFETIME if stage == "pending" else timedelta(minutes=get_settings().session_absolute_minutes)
    token = new_token()
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_token(token),
            stage=stage,
            mfa_method=mfa_method,
            created_at=now,
            last_seen_at=now,
            expires_at=now + lifetime,
            ip=source.ip,
            user_agent=source.user_agent,
        )
    )
    await db.flush()
    return token


async def lookup_session(db: AsyncSession, token: str | None, *, touch: bool = True) -> Lookup:
    if not token:
        return Lookup(None, None)
    session = await db.scalar(
        select(AuthSession).options(joinedload(AuthSession.user)).where(AuthSession.token_hash == hash_token(token))
    )
    if session is None:
        return Lookup(None, None)
    now = clock.now()
    if is_expired(session, now):
        await db.delete(session)
        await db.flush()
        return Lookup(None, session)
    if touch and now - session.last_seen_at >= TOUCH_EVERY:
        session.last_seen_at = now
    return Lookup(session, None)


async def end_sessions(db: AsyncSession, user_id: UUID, *, keep: UUID | None = None) -> list[AuthSession]:
    """Deletes the user's sessions except `keep`, and returns the deleted ones."""
    query = select(AuthSession).where(AuthSession.user_id == user_id)
    if keep is not None:
        query = query.where(AuthSession.id != keep)
    ended = list((await db.scalars(query)).all())
    for session in ended:
        await db.delete(session)
    await db.flush()
    return ended


async def delete_expired(db: AsyncSession, user_id: UUID) -> None:
    now = clock.now()
    await db.execute(
        delete(AuthSession).where(
            AuthSession.user_id == user_id,
            or_(AuthSession.expires_at <= now, AuthSession.last_seen_at <= now - _idle_limit()),
        )
    )


def _cookie_attributes(request: Request) -> dict:
    # Secure only under https: Uvicorn's --proxy-headers takes the scheme from X-Forwarded-Proto, and the dev
    # stack on plain http must still sign in. Lax, not Strict: a link from elsewhere opens the app signed in.
    return {"path": "/", "httponly": True, "samesite": "lax", "secure": request.url.scheme == "https"}


def set_cookie(response: Response, request: Request, token: str) -> None:
    max_age = get_settings().session_absolute_minutes * 60
    response.set_cookie(COOKIE, token, max_age=max_age, **_cookie_attributes(request))


def clear_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(COOKIE, **_cookie_attributes(request))

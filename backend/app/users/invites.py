"""Invite links: a token of 256 random bits that the Owner passes on, valid 7 days. Only its SHA-256 is stored."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import clock
from app.auth.sessions import hash_token, new_token
from app.users.models import UserInvite

INVITE_LIFETIME = timedelta(days=7)


async def put_invite(db: AsyncSession, user_id: UUID) -> tuple[str, datetime]:
    """Deletes the account's open invite and stores a new one. Returns the token (once) and when it expires."""
    await db.execute(delete(UserInvite).where(UserInvite.user_id == user_id))
    token = new_token()
    expires_at = clock.now() + INVITE_LIFETIME
    db.add(UserInvite(user_id=user_id, token_hash=hash_token(token), expires_at=expires_at))
    await db.flush()
    return token, expires_at


async def find_invite(db: AsyncSession, token: str) -> UserInvite | None:
    """The invite of this token, without a lock, expired ones included."""
    return await db.scalar(select(UserInvite).where(UserInvite.token_hash == hash_token(token)))

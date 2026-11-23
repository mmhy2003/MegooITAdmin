"""Invite links: a token of 256 random bits that the Owner passes on, valid 7 days. Only its SHA-256 is stored."""

from datetime import datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import Actor, ActorType, Result, record, source_of
from app.auth import clock
from app.auth.models import User
from app.auth.passwords import hash_password
from app.auth.service import Refusal, actor_of, auth_event, lock_user, target_of
from app.auth.sessions import create_session, hash_token, new_token
from app.users import actions
from app.users.models import UserInvite
from app.users.schemas import InviteAcceptIn, InviteInfoOut

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


async def check_invite(db: AsyncSession, token: str) -> InviteInfoOut:
    """Whose link it is, for the invite page. Unknown, used, expired or of a disabled account: 404."""
    invite = await find_invite(db, token)
    user = None if invite is None else await db.get(User, invite.user_id)
    if (
        user is None
        or invite.expires_at <= clock.now()
        or user.disabled_at is not None
        or user.password_hash is not None
    ):
        raise HTTPException(404, "invalid_invite")
    return InviteInfoOut(name=user.name, email=user.email)


async def accept_invite(db: AsyncSession, request: Request, body: InviteAcceptIn) -> str | Refusal:
    """Sets the account's first password, uses up the link and returns the token of a pending session.
    Every refusal answers the same 404 and records why."""
    refusal = Refusal(404, "invalid_invite")
    invite = await find_invite(db, body.token)
    if invite is not None:
        # Lock order: the user row, then its invite. A parallel accept waits here and then finds the invite gone.
        user = await lock_user(db, invite.user_id)
        invite = await db.scalar(
            select(UserInvite)
            .where(UserInvite.user_id == user.id, UserInvite.token_hash == hash_token(body.token))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    if invite is None:
        await record(
            db,
            auth_event(
                request,
                actions.USER_INVITE_REFUSED,
                Actor(type=ActorType.HUMAN, name="unknown"),
                mfa=False,
                result=Result.FAILURE,
                detail={"reason": actions.UNKNOWN},
            ),
        )
        return refusal

    reason = None
    if invite.expires_at <= clock.now():
        reason = actions.EXPIRED
    elif user.disabled_at is not None:
        reason = actions.DISABLED
    if reason is not None:
        await record(
            db,
            auth_event(
                request,
                actions.USER_INVITE_REFUSED,
                actor_of(user),
                target=target_of(user),
                mfa=False,
                result=Result.FAILURE,
                detail={"reason": reason},
            ),
        )
        return refusal

    user.password_hash = await hash_password(body.password)
    user.password_changed_at = clock.now()
    await db.delete(invite)
    token = await create_session(db, user, source_of(request), stage="pending")
    await record(
        db, auth_event(request, actions.USER_INVITE_ACCEPTED, actor_of(user), target=target_of(user), mfa=False)
    )
    return token

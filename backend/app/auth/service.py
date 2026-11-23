"""The auth flows, between the routes and the tables."""

from typing import Literal

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.sessions import lookup_session

Status = Literal["setup_required", "signed_out", "mfa_required", "enrolment_required", "active"]


async def status_of(db: AsyncSession, token: str | None) -> tuple[Status, User | None]:
    """Where the browser with this token stands. The user is returned only for an active session."""
    if not await db.scalar(select(exists().select_from(User))):
        return "setup_required", None
    session = (await lookup_session(db, token)).session
    if session is None:
        return "signed_out", None
    if session.stage == "active":
        return "active", session.user
    return ("mfa_required" if session.user.totp_secret is not None else "enrolment_required"), None

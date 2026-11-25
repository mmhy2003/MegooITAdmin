"""The route dependencies of signed-in requests: CurrentSession (pending or active) and CurrentUser (active only)."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.audit import Actor, Event, Result, Target, record, source_of
from app.auth import actions
from app.auth.models import AuthSession, User
from app.auth.sessions import BACKGROUND_HEADER, COOKIE, lookup_session
from app.core.db import DbSession

NOT_SIGNED_IN = "not_signed_in"


async def current_session(request: Request, db: DbSession) -> AuthSession:
    background = request.headers.get(BACKGROUND_HEADER) == "1"
    lookup = await lookup_session(db, request.cookies.get(COOKIE), touch=not background)
    if lookup.session is not None:
        return lookup.session
    expired = lookup.expired
    if expired is not None:
        # The raise below rolls the request back, so the deletion, and for a sign-in that was not finished in
        # time its event, are committed first.
        if expired.stage == "pending":
            user = expired.user
            await record(
                db,
                Event(
                    action=actions.MFA_FAILED,
                    actor=Actor.human(user.id, user.name),
                    target=Target(type="user", id=str(user.id), name=user.email),
                    result=Result.FAILURE,
                    result_detail={"reason": actions.EXPIRED},
                    source=source_of(request, auth_method="password", mfa=False),
                ),
            )
        await db.commit()
    raise HTTPException(401, NOT_SIGNED_IN)


CurrentSession = Annotated[AuthSession, Depends(current_session)]


async def current_user(session: CurrentSession) -> User:
    if session.stage != "active":
        raise HTTPException(401, NOT_SIGNED_IN)
    return session.user


CurrentUser = Annotated[User, Depends(current_user)]

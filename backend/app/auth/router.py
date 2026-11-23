"""The routes under /api/auth."""

from fastapi import APIRouter, Request

from app.auth import service
from app.auth.schemas import SessionStatusOut, UserOut
from app.auth.sessions import COOKIE
from app.core.db import DbSession

router = APIRouter(prefix="/auth")


@router.get("/session")
async def session_status(request: Request, db: DbSession) -> SessionStatusOut:
    # Public: the page gate asks it before anyone is signed in. Always 200.
    status, user = await service.status_of(db, request.cookies.get(COOKIE))
    return SessionStatusOut(status=status, user=UserOut.model_validate(user) if user else None)

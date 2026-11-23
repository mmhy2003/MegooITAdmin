"""The routes under /api/auth."""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.audit import audited
from app.auth import actions, service
from app.auth.schemas import SessionStatusOut, SetupIn, StatusOut, UserOut
from app.auth.sessions import COOKIE, set_cookie
from app.core.db import DbSession

router = APIRouter(prefix="/auth")


def refused(refusal: service.Refusal) -> JSONResponse:
    # Returned, not raised, so the transaction commits with the event of the refusal.
    return JSONResponse({"detail": refusal.reason}, status_code=refusal.status)


@router.get("/session")
async def session_status(request: Request, db: DbSession) -> SessionStatusOut:
    # Public: the page gate asks it before anyone is signed in. Always 200.
    status, user = await service.status_of(db, request.cookies.get(COOKIE))
    return SessionStatusOut(status=status, user=UserOut.model_validate(user) if user else None)


@router.post(
    "/setup",
    response_model=StatusOut,
    dependencies=[audited(actions.OWNER_CREATED, actions.SETUP_FAILED)],
)
async def setup(body: SetupIn, request: Request, response: Response, db: DbSession) -> StatusOut | JSONResponse:
    # Public: it claims a fresh install with the code from the host, before any account exists.
    result = await service.setup(db, request, body)
    if isinstance(result, service.Refusal):
        return refused(result)
    _, token = result
    set_cookie(response, request, token)
    return StatusOut(status="enrolment_required")

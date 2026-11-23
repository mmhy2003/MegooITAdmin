"""The routes under /api/auth."""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.audit import audited
from app.auth import actions, service
from app.auth.deps import CurrentSession
from app.auth.schemas import (
    CodeIn,
    ConfirmIn,
    ConfirmOut,
    EnrolIn,
    EnrolOut,
    LoginIn,
    SessionStatusOut,
    SetupIn,
    StatusOut,
    UserOut,
)
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


@router.post(
    "/login",
    response_model=StatusOut,
    dependencies=[audited(actions.PASSWORD_ACCEPTED, actions.SIGN_IN_FAILED)],
)
async def login(body: LoginIn, request: Request, response: Response, db: DbSession) -> StatusOut | JSONResponse:
    # Public: the password step, before anyone is signed in. It gives only a pending session.
    result = await service.login(db, request, body)
    if isinstance(result, service.Refusal):
        return refused(result)
    token, status = result
    set_cookie(response, request, token)
    return StatusOut(status=status)


@router.post(
    "/login/mfa",
    response_model=StatusOut,
    dependencies=[audited(actions.SIGN_IN, actions.MFA_FAILED)],
)
async def login_mfa(
    body: CodeIn, request: Request, response: Response, db: DbSession, session: CurrentSession
) -> StatusOut | JSONResponse:
    # Pending: the code step finishes the sign-in that the password step started.
    result = await service.verify_second_factor(db, request, session, body)
    if isinstance(result, service.Refusal):
        return refused(result)
    set_cookie(response, request, result)
    return StatusOut(status="active")


@router.post(
    "/mfa/enrol",
    response_model=EnrolOut,
    dependencies=[audited(actions.MFA_ENROLMENT_STARTED, actions.MFA_FAILED)],
)
async def enrol(body: EnrolIn, request: Request, db: DbSession, session: CurrentSession) -> EnrolOut | JSONResponse:
    # Pending: an account without an authenticator enrols before its first sign-in. Active: it replaces it.
    result = await service.start_enrolment(db, request, session, body)
    if isinstance(result, service.Refusal):
        return refused(result)
    return result


@router.post(
    "/mfa/enrol/confirm",
    response_model=ConfirmOut,
    dependencies=[audited(actions.MFA_ENROLLED, actions.MFA_FAILED)],
)
async def confirm_enrolment(
    body: ConfirmIn, request: Request, response: Response, db: DbSession, session: CurrentSession
) -> ConfirmOut | JSONResponse:
    # Pending: confirming the first authenticator finishes the sign-in, under a new token.
    result = await service.confirm_enrolment(db, request, session, body)
    if isinstance(result, service.Refusal):
        return refused(result)
    codes, token = result
    if token is not None:
        set_cookie(response, request, token)
    return ConfirmOut(recovery_codes=codes)

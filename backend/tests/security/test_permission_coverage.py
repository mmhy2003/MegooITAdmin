"""Every signed-in route says who may call it, except the few any signed-in person may use, pinned here."""

from fastapi import APIRouter, Depends, FastAPI
from routes import access_requirement, api_routes, undeclared_routes

from app.access.deps import require_grant, require_group_visible, require_owner
from app.access.permissions import Permission
from app.auth.deps import CurrentUser
from app.main import create_app

# Routes any signed-in person may call: each acts only on the person's own account.
ANY_SIGNED_IN: dict[str, str] = {
    "GET /api/auth/me": "a person reads their own account",
    "GET /api/auth/sessions": "a person lists their own sessions",
    "DELETE /api/auth/sessions/{session_id}": "a person ends one of their own sessions",
    "POST /api/auth/password": "a person changes their own password",
    "POST /api/auth/recovery-codes": "a person replaces their own recovery codes",
}


def test_every_signed_in_route_declares_who_may_call_it():
    undeclared = undeclared_routes(create_app(), ANY_SIGNED_IN)
    assert undeclared == [], (
        f"{', '.join(undeclared)} say nothing about who may call them: add Depends(require_owner), "
        "require_grant(...) or require_group_visible(...), or pin the route here with a reason"
    )


def test_any_signed_in_names_only_real_routes():
    real = {f"{method} {route.path}" for route in api_routes(create_app()) for method in route.methods}
    assert set(ANY_SIGNED_IN) <= real, f"pinned routes the app does not have: {sorted(set(ANY_SIGNED_IN) - real)}"


def sample_app() -> FastAPI:
    app = FastAPI()

    @app.get("/open")
    async def open_route() -> None: ...

    @app.get("/mine")
    async def mine(user: CurrentUser) -> None: ...

    @app.get("/admin", dependencies=[Depends(require_owner)])
    async def admin() -> None: ...

    @app.get("/g/{group_id}", dependencies=[Depends(require_grant(Permission.VIEW_LOGS))])
    async def logs() -> None: ...

    @app.get("/v/{group_id}", dependencies=[Depends(require_group_visible())])
    async def visible() -> None: ...

    router = APIRouter(prefix="/users")

    @router.get("")
    async def users(user: CurrentUser) -> None: ...

    app.include_router(router, dependencies=[Depends(require_owner)])
    return app


def test_the_check_reports_an_undeclared_route_of_a_sample_app():
    app = sample_app()
    assert undeclared_routes(app, {}) == ["GET /mine"]
    assert undeclared_routes(app, {"GET /mine": "reason"}) == []


def test_access_requirement_names_what_the_route_needs():
    requirements = {context.path: access_requirement(context) for context in api_routes(sample_app())}
    assert requirements == {
        "/open": None,
        "/mine": None,
        "/admin": "owner",
        "/g/{group_id}": "view_logs",
        "/v/{group_id}": "group",
        "/users": "owner",
    }

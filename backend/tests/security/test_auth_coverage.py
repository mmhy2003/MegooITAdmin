"""Every route needs an active session, except the few pinned here with their reason."""

from fastapi import APIRouter, Depends, FastAPI
from routes import api_routes, unguarded_routes

from app.audit import audited
from app.auth.deps import CurrentSession, CurrentUser, current_user
from app.main import create_app

# Routes that work without any session. Adding one is a visible change to the security suite.
PUBLIC: dict[str, str] = {
    "GET /api/health": "liveness for Compose and Caddy; it reveals nothing",
    "GET /api/auth/session": "the page gate asks it which page to show before anyone is signed in",
    "POST /api/auth/setup": "claims a fresh install with the one-time code from the host, before any account exists",
    "POST /api/auth/login": "the password step of sign-in; it gives only a pending session",
}
# Routes that also work with a pending session (password right, second factor still to come).
PENDING: dict[str, str] = {}


def test_every_route_needs_an_active_session_or_is_pinned():
    unguarded = unguarded_routes(create_app(), PUBLIC, PENDING)
    assert unguarded == [], (
        f"{', '.join(unguarded)} work without an active session: take `user: CurrentUser` in the handler, "
        "include the router with dependencies=[Depends(current_user)], or pin the route here with a reason"
    )


def test_the_pinned_lists_name_only_real_routes():
    real = {f"{method} {route.path}" for route in api_routes(create_app()) for method in route.methods}
    pinned = set(PUBLIC) | set(PENDING)
    assert pinned <= real, f"pinned routes the app does not have: {sorted(pinned - real)}"
    assert not set(PUBLIC) & set(PENDING), "a route is pinned twice"


def sample_app() -> FastAPI:
    app = FastAPI()

    @app.get("/open")
    async def open_route() -> None: ...

    @app.get("/mine", dependencies=[Depends(current_user)])
    async def mine() -> None: ...

    @app.get("/me")
    async def me(user: CurrentUser) -> None: ...

    @app.post("/finish")
    async def finish(session: CurrentSession) -> None: ...

    # A route dependency with scope="function", as audited(...) is, beside the session one.
    @app.post("/things", dependencies=[audited("thing.created"), Depends(current_user)])
    async def things() -> None: ...

    router = APIRouter(prefix="/servers")

    @router.get("")
    async def servers() -> None: ...

    app.include_router(router, dependencies=[Depends(current_user)])
    return app


def test_the_check_reports_an_unprotected_route_of_a_sample_app():
    app = sample_app()
    assert unguarded_routes(app, {}, {}) == ["GET /open (none)", "POST /finish (pending)"]
    assert unguarded_routes(app, {"GET /open": "reason"}, {"POST /finish": "reason"}) == []
    # A pending route is not public, and a public list does not cover a pending route.
    assert unguarded_routes(app, {"POST /finish": "reason"}, {"GET /open": "reason"}) == [
        "GET /open (none)",
        "POST /finish (pending)",
    ]

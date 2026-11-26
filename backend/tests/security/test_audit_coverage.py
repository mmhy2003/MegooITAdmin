"""Every state-changing route declares the audit events it records, so the guard can roll back one that does not."""

from fastapi import APIRouter, FastAPI, WebSocket
from routes import api_routes, declared_actions, unaudited_routes, unknown_routes
from test_socket_coverage import SOCKETS

from app.audit import audited
from app.main import create_app

# A POST, PUT, PATCH or DELETE route that needs no audit event, with the reason. Adding one is a visible
# change to the security suite.
EXEMPT: dict[str, str] = {
    "POST /api/auth/invite/check": "it only reads; POST keeps the token out of addresses and logs",
}


def test_every_state_changing_route_declares_its_audit_actions():
    missing = unaudited_routes(create_app(), EXEMPT)
    assert missing == [], (
        f"{', '.join(missing)} change state but declare no audit event: add dependencies=[audited('…')] "
        "to the route and call record() in its handler"
    )


def test_the_app_has_no_route_the_check_does_not_understand():
    unknown = unknown_routes(create_app(), SOCKETS)
    assert unknown == [], (
        f"{', '.join(unknown)}: the audit guard covers HTTP routes only. Pin a WebSocket route in SOCKETS of "
        "test_socket_coverage.py, and extend this check before adding a mount"
    )


def test_exempt_lists_only_real_routes():
    real = {f"{method} {route.path}" for route in api_routes(create_app()) for method in route.methods}
    assert set(EXEMPT) <= real, f"EXEMPT names routes the app does not have: {sorted(set(EXEMPT) - real)}"


def sample_app() -> FastAPI:
    app = FastAPI()

    @app.post("/things")
    async def create_thing() -> None: ...

    @app.put("/things/{id}", dependencies=[audited("thing.updated")])
    async def update_thing(id: int) -> None: ...

    @app.get("/things")
    async def list_things() -> list[str]:
        return []

    return app


def test_the_check_reports_an_undeclared_route_of_a_sample_app():
    app = sample_app()
    assert unaudited_routes(app, {}) == ["POST /things"]
    assert unaudited_routes(app, {"POST /things": "reason"}) == []


def test_the_check_finds_the_actions_of_a_router_dependency():
    router = APIRouter(prefix="/things")

    @router.post("")
    async def create_thing() -> None: ...

    api = APIRouter(prefix="/api")
    api.include_router(router, dependencies=[audited("thing.created")])
    app = FastAPI()
    app.include_router(api)
    (route,) = api_routes(app)
    assert route.path == "/api/things"
    assert declared_actions(route) == {"thing.created"}
    assert unaudited_routes(app, {}) == []


def test_the_check_reports_websocket_routes_and_mounts():
    router = APIRouter(prefix="/api")

    @router.websocket("/ws")
    async def ws(websocket: WebSocket) -> None: ...

    app = FastAPI()
    app.include_router(router)
    app.mount("/static", FastAPI())
    assert unknown_routes(app) == ["APIWebSocketRoute /api/ws", "Mount /static"]

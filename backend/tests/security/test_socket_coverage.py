"""Every WebSocket route is pinned here and opens through the shared handshake of app/auth/socket.py, so none can
skip the Origin check or the active session."""

from fastapi import APIRouter, FastAPI, WebSocket
from routes import socket_routes, unknown_routes

from app.auth.socket import SocketSession, open_socket, signed_in_socket
from app.main import create_app

# Every WebSocket route of the app, with what it carries. Adding one is a visible change to the security suite.
SOCKETS: dict[str, str] = {}


def without_handshake(app: FastAPI) -> list[str]:
    return sorted(
        context.path
        for context in socket_routes(app)
        if getattr(context.original_route.endpoint, "socket_handshake", None) is not open_socket
    )


def test_every_socket_is_pinned():
    paths = {context.path for context in socket_routes(create_app())}
    assert paths == set(SOCKETS), (
        f"unpinned sockets: {sorted(paths - set(SOCKETS))}, pinned but missing: {sorted(set(SOCKETS) - paths)}"
    )


def test_every_socket_uses_the_shared_handshake():
    missing = without_handshake(create_app())
    assert missing == [], f"{', '.join(missing)}: decorate the handler with @signed_in_socket from app.auth.socket"


def test_the_checks_see_a_socket_of_a_sample_app():
    router = APIRouter(prefix="/api/ws")

    @router.websocket("/a")
    @signed_in_socket
    async def a(websocket: WebSocket, signed: SocketSession) -> None: ...

    @router.websocket("/b")
    async def b(websocket: WebSocket) -> None: ...

    app = FastAPI()
    app.include_router(router)
    assert sorted(context.path for context in socket_routes(app)) == ["/api/ws/a", "/api/ws/b"]
    assert without_handshake(app) == ["/api/ws/b"]
    assert unknown_routes(app, {"/api/ws/a": "r"}) == ["APIWebSocketRoute /api/ws/b"]

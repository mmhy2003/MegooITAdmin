"""The handshake of every WebSocket: the Origin check and the active session. The live metrics use it now; live logs
and terminals reuse it later.

A socket is not a request: it never moves last_seen_at, so an open page still signs out after the idle limit. It
holds no database session either; the handshake and each recheck open a short one."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import WebSocket

from app.access.deps import load_access
from app.access.permissions import Access
from app.auth.models import User
from app.auth.sessions import COOKIE, lookup_session
from app.core.db import SessionLocal

NOT_SIGNED_IN_CLOSE = 4401
# Uvicorn answers a close before accept with HTTP 403.
POLICY_CLOSE = 1008


@dataclass(frozen=True)
class SocketSession:
    token: str
    session_id: UUID
    user: User
    access: Access


def same_origin(websocket: WebSocket) -> bool:
    """A request without Origin is not a browser's, so it carries no ambient cookie: allowed. Otherwise the Origin's
    host must be the Host header; "null" (a sandboxed or file page) is foreign."""
    origin = websocket.headers.get("origin")
    if origin is None:
        return True
    host = websocket.headers.get("host", "").lower()
    return bool(host) and urlsplit(origin).netloc.lower() == host


async def _signed(token: str | None) -> SocketSession | None:
    """The active session of the token with fresh user and access, or None. An expired session's row is deleted."""
    async with SessionLocal() as db:
        lookup = await lookup_session(db, token, touch=False)
        session = lookup.session
        access = None if session is None or session.stage != "active" else await load_access(db, session.user)
        await db.commit()
    if access is None:
        return None
    return SocketSession(token=token, session_id=session.id, user=session.user, access=access)


async def open_socket(websocket: WebSocket) -> SocketSession | None:
    """Accepts the socket of a signed-in person and returns their session. A foreign Origin is refused with 403; no
    active session closes with 4401 after accept, so the browser sees the code. None in both cases."""
    if not same_origin(websocket):
        await websocket.close(code=POLICY_CLOSE)
        return None
    signed = await _signed(websocket.cookies.get(COOKIE))
    await websocket.accept()
    if signed is None:
        await websocket.close(code=NOT_SIGNED_IN_CLOSE)
    return signed


async def recheck(signed: SocketSession) -> SocketSession | None:
    """The session again, without touching it: None when it ended or is no longer active, else a SocketSession with
    freshly loaded user and access."""
    return await _signed(signed.token)


def signed_in_socket(handler: Callable[[WebSocket, SocketSession], Awaitable[None]]):
    """Makes `handler(websocket, signed)` a WebSocket endpoint that runs only after open_socket accepted."""

    async def endpoint(websocket: WebSocket) -> None:
        signed = await open_socket(websocket)
        if signed is not None:
            await handler(websocket, signed)

    # Not functools.wraps: FastAPI would read the handler's two-parameter signature through __wrapped__.
    endpoint.__name__ = handler.__name__
    endpoint.__doc__ = handler.__doc__
    # Read by tests/security/test_socket_coverage.py.
    endpoint.socket_handshake = open_socket
    return endpoint

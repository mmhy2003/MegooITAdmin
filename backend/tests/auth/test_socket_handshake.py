"""The handshake every WebSocket shares: the Origin check and the active session, without touching it."""

import pytest
from auth_helpers import EMAIL, PASSWORD, add_grant, make_group, make_user, sign_in
from fastapi import APIRouter, FastAPI, WebSocket
from socket_helpers import close_code, connect, serving
from sqlalchemy import select
from websockets.exceptions import InvalidStatus

from app.access.deps import load_access
from app.auth.models import AuthSession, User
from app.auth.sessions import COOKIE
from app.auth.socket import NOT_SIGNED_IN_CLOSE, SocketSession, recheck, signed_in_socket
from app.core.db import SessionLocal

PATH = "/api/ws/echo"


def echo_app() -> FastAPI:
    router = APIRouter()

    @router.websocket(PATH)
    @signed_in_socket
    async def echo(ws: WebSocket, signed: SocketSession) -> None:
        await ws.send_json({"user": str(signed.user.id)})

    app = FastAPI()
    app.include_router(router)
    return app


async def session_rows() -> list[AuthSession]:
    async with SessionLocal() as db:
        return list((await db.scalars(select(AuthSession))).all())


async def signed_in_cookie(api, clock, **account) -> str:
    _, secret = await make_user(**account)
    await sign_in(api, clock, secret, email=account.get("email", EMAIL))
    return api.cookies[COOKIE]


async def test_a_socket_without_a_cookie_closes_with_4401(api):
    async with serving(echo_app()) as base, connect(base, PATH) as ws:
        assert await close_code(ws) == NOT_SIGNED_IN_CLOSE == 4401


async def test_a_pending_session_closes_with_4401(api):
    await make_user()
    response = await api.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200, response.text
    async with serving(echo_app()) as base, connect(base, PATH, api.cookies[COOKIE]) as ws:
        assert await close_code(ws) == 4401


async def test_an_expired_session_closes_with_4401_and_is_deleted(api, clock):
    cookie = await signed_in_cookie(api, clock)
    clock.advance(minutes=61)
    async with serving(echo_app()) as base, connect(base, PATH, cookie) as ws:
        assert await close_code(ws) == 4401
    assert await session_rows() == []


async def test_an_active_session_is_accepted_and_not_touched(api, clock):
    cookie = await signed_in_cookie(api, clock)
    (before,) = await session_rows()
    clock.advance(minutes=2)
    async with serving(echo_app()) as base, connect(base, PATH, cookie) as ws:
        assert await ws.recv() == f'{{"user":"{before.user_id}"}}'
    (after,) = await session_rows()
    assert after.last_seen_at == before.last_seen_at


@pytest.mark.parametrize("origin", ["http://evil.example", "null"])
async def test_a_foreign_origin_is_refused_with_403(api, clock, origin):
    cookie = await signed_in_cookie(api, clock)
    async with serving(echo_app()) as base:
        with pytest.raises(InvalidStatus) as refused:
            async with connect(base, PATH, cookie, origin=origin):
                pass
    assert refused.value.response.status_code == 403


async def test_a_socket_without_an_origin_is_accepted(api, clock):
    cookie = await signed_in_cookie(api, clock)
    async with serving(echo_app()) as base, connect(base, PATH, cookie, origin=None) as ws:
        assert "user" in await ws.recv()


async def test_recheck_sees_an_ended_session_and_fresh_access(api, clock):
    cookie = await signed_in_cookie(api, clock, platform_role=None)
    (row,) = await session_rows()
    async with SessionLocal() as db:
        user = await db.get(User, row.user_id)
        signed = SocketSession(token=cookie, session_id=row.id, user=user, access=await load_access(db, user))
    assert signed.access.groups == {}

    group = await make_group("web")
    await add_grant(row.user_id, group.id, "operator")
    fresh = await recheck(signed)
    assert fresh is not None and fresh.session_id == row.id and fresh.user.id == row.user_id
    assert set(fresh.access.groups) == {group.id}

    async with SessionLocal() as db:
        await db.delete(await db.get(AuthSession, row.id))
        await db.commit()
    assert await recheck(signed) is None

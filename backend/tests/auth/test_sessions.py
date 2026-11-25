import hashlib
from datetime import timedelta

import pytest
from auth_helpers import events, make_user
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from starlette.requests import Request
from starlette.responses import Response

from app.audit import Source
from app.auth import sessions
from app.auth.deps import CurrentUser
from app.auth.models import AuthSession
from app.core.db import SessionLocal

pytestmark = pytest.mark.usefixtures("clean_auth")

SOURCE = Source(ip="192.0.2.7", user_agent="pytest")


async def start(user, stage="active", mfa_method="totp") -> str:
    async with SessionLocal() as db:
        token = await sessions.create_session(
            db, user, SOURCE, stage=stage, mfa_method=mfa_method if stage == "active" else None
        )
        await db.commit()
    return token


async def look(token: str | None) -> sessions.Lookup:
    async with SessionLocal() as db:
        found = await sessions.lookup_session(db, token)
        await db.commit()
    return found


async def rows() -> list[AuthSession]:
    async with SessionLocal() as db:
        return list((await db.scalars(select(AuthSession).order_by(AuthSession.created_at))).all())


async def test_a_session_is_found_by_its_token_and_only_its_hash_is_stored(clock):
    user, _ = await make_user()
    token = await start(user)
    found = await look(token)
    assert found.session is not None and found.expired is None
    assert found.session.user.email == user.email
    assert found.session.stage == "active"
    assert str(found.session.ip) == "192.0.2.7" and found.session.user_agent == "pytest"
    (row,) = await rows()
    assert row.token_hash == hashlib.sha256(token.encode()).digest()
    assert token.encode() not in row.token_hash
    assert (await look("not-a-token")).session is None
    assert (await look(None)).session is None


async def test_an_active_session_ends_after_an_hour_without_a_request(clock):
    user, _ = await make_user()
    token = await start(user)
    clock.advance(minutes=60)
    found = await look(token)
    assert found.session is None
    assert found.expired is not None and found.expired.stage == "active"
    assert await rows() == []


async def test_a_request_every_50_minutes_keeps_it_alive(clock):
    user, _ = await make_user()
    token = await start(user)
    for _ in range(5):
        clock.advance(minutes=50)
        assert (await look(token)).session is not None


async def test_an_active_session_ends_twelve_hours_after_sign_in(clock):
    user, _ = await make_user()
    token = await start(user)
    for _ in range(14):
        clock.advance(minutes=50)
        assert (await look(token)).session is not None
    clock.advance(minutes=20)  # 12 hours since sign-in
    assert (await look(token)).session is None
    assert await rows() == []


async def test_a_pending_session_ends_after_ten_minutes(clock):
    user, _ = await make_user()
    token = await start(user, stage="pending")
    clock.advance(minutes=9, seconds=59)
    assert (await look(token)).session is not None
    clock.advance(seconds=1)
    found = await look(token)
    assert found.session is None and found.expired.stage == "pending"
    assert await rows() == []


async def test_last_seen_at_moves_at_most_once_a_minute(clock):
    user, _ = await make_user()
    token = await start(user)
    signed_in = clock.now
    clock.advance(seconds=59)
    await look(token)
    assert (await rows())[0].last_seen_at == signed_in
    clock.advance(seconds=1)
    await look(token)
    assert (await rows())[0].last_seen_at == signed_in + timedelta(minutes=1)


async def test_end_sessions_keeps_the_given_one(clock):
    user, _ = await make_user()
    other, _ = await make_user(email="other@example.com")
    await start(user)
    await start(user, stage="pending")
    kept = await start(user)
    others = await start(other)
    kept_id = (await look(kept)).session.id
    async with SessionLocal() as db:
        ended = await sessions.end_sessions(db, user.id, keep=kept_id)
        await db.commit()
    assert len(ended) == 2 and kept_id not in {s.id for s in ended}
    assert {s.id for s in await rows()} == {kept_id, (await look(others)).session.id}


async def test_delete_expired_removes_only_expired_rows(clock):
    user, _ = await make_user()
    other, _ = await make_user(email="other@example.com")
    await start(user)
    await start(other)
    clock.advance(minutes=30)
    fresh = await start(user)
    clock.advance(minutes=30)  # the first two are idle for an hour now
    async with SessionLocal() as db:
        await sessions.delete_expired(db, user.id)
        await db.commit()
    remaining = await rows()
    assert len(remaining) == 2
    assert {s.user_id for s in remaining} == {user.id, other.id}
    assert (await look(fresh)).session is not None


def request(scheme: str) -> Request:
    return Request(
        {
            "type": "http",
            "scheme": scheme,
            "method": "GET",
            "server": ("test", 443 if scheme == "https" else 80),
            "path": "/",
            "query_string": b"",
            "headers": [],
        }
    )


def set_cookie_header(response: Response) -> str:
    (header,) = [value for name, value in response.raw_headers if name == b"set-cookie"]
    return header.decode()


def test_the_cookie_is_httponly_lax_path_root_with_the_absolute_max_age():
    response = Response()
    sessions.set_cookie(response, request("http"), "the-token")
    header = set_cookie_header(response)
    assert header.startswith("megoo_session=the-token;")
    parts = {part.strip().lower() for part in header.split(";")}
    assert {"httponly", "samesite=lax", "path=/", "max-age=43200"} <= parts
    assert "secure" not in parts


def test_the_cookie_is_secure_under_https():
    response = Response()
    sessions.set_cookie(response, request("https"), "the-token")
    assert "secure" in {part.strip().lower() for part in set_cookie_header(response).split(";")}


def test_clear_cookie_expires_it():
    response = Response()
    sessions.clear_cookie(response, request("https"))
    header = set_cookie_header(response)
    parts = {part.strip().lower() for part in header.split(";")}
    assert header.startswith('megoo_session="";')
    assert {"max-age=0", "httponly", "samesite=lax", "path=/", "secure"} <= parts


def probe_app() -> FastAPI:
    app = FastAPI()

    @app.get("/probe")
    async def probe(user: CurrentUser) -> dict[str, str]:
        return {"email": user.email}

    return app


async def get_probe(token: str | None, *, background: str | None = None):
    transport = ASGITransport(app=probe_app())
    cookies = {sessions.COOKIE: token} if token else {}
    headers = {sessions.BACKGROUND_HEADER: background} if background is not None else {}
    async with AsyncClient(transport=transport, base_url="http://test", cookies=cookies) as client:
        return await client.get("/probe", headers=headers)


async def test_a_pending_session_cannot_call_a_current_user_route(clock):
    user, _ = await make_user()
    pending = await get_probe(await start(user, stage="pending"))
    assert pending.status_code == 401 and pending.json() == {"detail": "not_signed_in"}
    assert (await get_probe(None)).status_code == 401
    active = await get_probe(await start(user))
    assert active.status_code == 200 and active.json() == {"email": user.email}


async def test_an_expired_pending_session_records_mfa_failed_expired(clock):
    user, _ = await make_user()
    token = await start(user, stage="pending")
    clock.advance(minutes=10)
    response = await get_probe(token)
    assert response.status_code == 401 and response.json() == {"detail": "not_signed_in"}
    (event,) = await events("auth.mfa_failed")
    assert event.result == "failure"
    assert event.result_detail == {"reason": "expired"}
    assert event.actor_id == str(user.id) and event.target_id == str(user.id)
    assert event.mfa is False
    assert await rows() == []


async def test_an_expired_active_session_records_nothing_and_is_deleted(clock):
    user, _ = await make_user()
    token = await start(user)
    clock.advance(minutes=60)
    assert (await get_probe(token)).status_code == 401
    assert await events("auth.mfa_failed") == []
    async with SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(AuthSession)) == 0


async def test_a_background_request_does_not_move_last_seen_at(clock):
    user, _ = await make_user()
    token = await start(user)
    signed_in = clock.now
    clock.advance(minutes=5)
    assert (await get_probe(token, background="1")).status_code == 200
    assert (await rows())[0].last_seen_at == signed_in


async def test_a_session_kept_only_by_background_requests_ends_after_the_idle_limit(clock):
    user, _ = await make_user()
    token = await start(user)
    for _ in range(2):
        clock.advance(minutes=20)
        assert (await get_probe(token, background="1")).status_code == 200
    clock.advance(minutes=20)  # 60 minutes without a foreground request
    response = await get_probe(token, background="1")
    assert response.status_code == 401 and response.json() == {"detail": "not_signed_in"}
    assert await rows() == []


@pytest.mark.parametrize("background", [None, "0"])
async def test_a_request_without_the_header_still_moves_last_seen_at(clock, background):
    user, _ = await make_user()
    token = await start(user)
    signed_in = clock.now
    clock.advance(minutes=5)
    assert (await get_probe(token, background=background)).status_code == 200
    assert (await rows())[0].last_seen_at == signed_in + timedelta(minutes=5)


async def test_lookup_without_touch_leaves_last_seen_at(clock):
    user, _ = await make_user()
    token = await start(user)
    signed_in = clock.now
    clock.advance(minutes=5)
    async with SessionLocal() as db:
        found = await sessions.lookup_session(db, token, touch=False)
        await db.commit()
    assert found.session is not None
    assert (await rows())[0].last_seen_at == signed_in

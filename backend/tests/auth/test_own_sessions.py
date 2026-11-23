from auth_helpers import PASSWORD, events, make_user, sign_in
from httpx import AsyncClient
from sqlalchemy import select

from app.auth import sessions
from app.auth.models import AuthSession
from app.core.db import SessionLocal


def other_client(api) -> AsyncClient:
    """A second browser on the same app."""
    return AsyncClient(transport=api._transport, base_url="http://test")


async def session_rows() -> list[AuthSession]:
    async with SessionLocal() as db:
        return list((await db.scalars(select(AuthSession))).all())


async def row_of(client) -> AuthSession:
    token_hash = sessions.hash_token(client.cookies.get(sessions.COOKIE))
    (row,) = [row for row in await session_rows() if row.token_hash == token_hash]
    return row


async def test_sign_out_deletes_the_session_and_clears_the_cookie(api, clock):
    user, secret = await make_user()
    await sign_in(api, clock, secret)

    response = await api.post("/api/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"status": "signed_out"}
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f'{sessions.COOKIE}=""') and "Max-Age=0" in cookie
    assert "HttpOnly" in cookie and "Path=/" in cookie
    assert await session_rows() == []

    (event,) = await events("auth.sign_out")
    assert (event.actor_id, event.target_id, event.result, event.mfa) == (str(user.id), str(user.id), "success", True)
    assert (await api.get("/api/auth/session")).json()["status"] == "signed_out"


async def test_a_pending_session_can_sign_out(api):
    user, _ = await make_user()
    response = await api.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert response.json() == {"status": "mfa_required"}

    response = await api.post("/api/auth/logout")
    assert response.status_code == 200
    assert await session_rows() == []
    (event,) = await events("auth.sign_out")
    assert (event.actor_id, event.mfa) == (str(user.id), False)


async def test_me_shows_the_user_and_the_second_factor(api, clock):
    user, secret = await make_user(recovery_codes=["AAAA-BBBB-CCCC-DDDD", "EEEE-FFFF-GGGG-HHHH"])
    created = clock.now
    await sign_in(api, clock, secret)

    response = await api.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json() == {
        "user": {"id": str(user.id), "name": user.name, "email": user.email, "platform_role": "owner"},
        "password_changed_at": created.isoformat().replace("+00:00", "Z"),
        "totp_confirmed_at": created.isoformat().replace("+00:00", "Z"),
        "recovery_codes_left": 2,
    }


async def test_sessions_lists_the_persons_sessions_and_marks_this_one(api, clock):
    _, secret = await make_user()
    await sign_in(api, clock, secret)
    async with other_client(api) as other, other_client(api) as pending:
        await sign_in(other, clock, secret)
        # A sign-in that stopped at the password is not one of the sessions shown.
        await pending.post("/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
        mine, theirs = await row_of(api), await row_of(other)

        response = await other.get("/api/auth/sessions")
    assert response.status_code == 200
    listed = response.json()
    # Newest first.
    assert [(s["id"], s["current"]) for s in listed] == [(str(theirs.id), True), (str(mine.id), False)]
    assert listed[0]["ip"] == "127.0.0.1"
    assert listed[0]["mfa_method"] == "totp"
    assert set(listed[0]) == {"id", "current", "created_at", "last_seen_at", "ip", "user_agent", "mfa_method"}


async def test_sessions_leaves_out_expired_ones_without_deleting_them(api, clock):
    _, secret = await make_user()
    await sign_in(api, clock, secret)
    async with other_client(api) as other:
        await sign_in(other, clock, secret)
    # This one is used within the idle limit; the other one is not.
    clock.advance(minutes=58)
    assert (await api.get("/api/auth/me")).status_code == 200
    clock.advance(minutes=3)

    response = await api.get("/api/auth/sessions")
    assert [s["current"] for s in response.json()] == [True]
    assert len(await session_rows()) == 2


async def test_revoke_ends_another_session(api, clock):
    user, secret = await make_user()
    await sign_in(api, clock, secret)
    async with other_client(api) as other:
        await sign_in(other, clock, secret)
        theirs = await row_of(other)

        response = await api.delete(f"/api/auth/sessions/{theirs.id}")
        assert response.status_code == 204
        assert response.content == b""
        assert (await other.get("/api/auth/me")).status_code == 401

    assert [row.id for row in await session_rows()] == [(await row_of(api)).id]
    (event,) = await events("auth.session_revoked")
    assert (event.actor_id, event.target_type, event.target_id, event.mfa) == (
        str(user.id),
        "auth_session",
        str(theirs.id),
        True,
    )


async def test_revoke_refuses_the_current_session(api, clock):
    _, secret = await make_user()
    await sign_in(api, clock, secret)
    mine = await row_of(api)

    response = await api.delete(f"/api/auth/sessions/{mine.id}")
    assert (response.status_code, response.json()) == (409, {"detail": "current_session"})
    assert len(await session_rows()) == 1
    assert await events("auth.session_revoked") == []


async def test_revoke_answers_404_for_someone_elses_session(api, clock):
    _, secret = await make_user()
    _, other_secret = await make_user(email="other@example.com", platform_role=None)
    await sign_in(api, clock, secret)
    async with other_client(api) as other:
        await sign_in(other, clock, other_secret, email="other@example.com")
        theirs = await row_of(other)

        response = await api.delete(f"/api/auth/sessions/{theirs.id}")
        assert (response.status_code, response.json()) == (404, {"detail": "not_found"})
        assert (await other.get("/api/auth/me")).status_code == 200

    missing = await api.delete("/api/auth/sessions/00000000-0000-0000-0000-000000000000")
    assert (missing.status_code, missing.json()) == (404, {"detail": "not_found"})
    assert await events("auth.session_revoked") == []


async def test_me_needs_an_active_session(api):
    user, _ = await make_user()
    await api.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})

    for response in (await api.get("/api/auth/me"), await api.get("/api/auth/sessions")):
        assert (response.status_code, response.json()) == (401, {"detail": "not_signed_in"})

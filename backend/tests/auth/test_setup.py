import asyncio

from auth_helpers import PASSWORD, actions, events, load_user, make_user, put_setup_code
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth import sessions
from app.auth.models import SetupCode
from app.core.db import SessionLocal
from app.main import create_app

CODE = "ABCD-EFGH-IJKL-MNOP"
BODY = {"code": CODE, "name": "  Olive Owner ", "email": "Owner@Example.COM", "password": PASSWORD}


async def setup_row() -> SetupCode | None:
    async with SessionLocal() as session:
        return await session.scalar(select(SetupCode))


async def test_a_wrong_code_is_refused_and_counted(api):
    await put_setup_code(CODE)
    response = await api.post("/api/auth/setup", json={**BODY, "code": "AAAA-AAAA-AAAA-AAAA"})
    assert response.status_code == 401
    assert response.json() == {"detail": "wrong_setup_code"}
    assert (await setup_row()).failed_attempts == 1
    (event,) = await events("auth.setup_failed")
    assert (event.result, event.result_detail) == ("failure", {"reason": "wrong_code"})
    assert (event.actor_type, event.actor_id, event.actor_name) == ("human", None, "Owner@Example.COM")
    assert sessions.COOKIE not in response.cookies


async def test_the_fifth_wrong_code_deletes_it(api):
    await put_setup_code(CODE, failed_attempts=4)
    response = await api.post("/api/auth/setup", json={**BODY, "code": "AAAA-AAAA-AAAA-AAAA"})
    assert response.status_code == 401
    assert response.json() == {"detail": "no_setup_code"}
    assert await setup_row() is None
    # Even the right code is too late now.
    response = await api.post("/api/auth/setup", json=BODY)
    assert response.json() == {"detail": "no_setup_code"}


async def test_without_a_code_setup_is_refused(api):
    response = await api.post("/api/auth/setup", json=BODY)
    assert response.status_code == 401
    assert response.json() == {"detail": "no_setup_code"}
    (event,) = await events("auth.setup_failed")
    assert event.result_detail == {"reason": "no_code"}


async def test_the_right_code_creates_the_owner_and_a_pending_session(api):
    await put_setup_code(CODE)
    response = await api.post("/api/auth/setup", json={**BODY, "code": "abcd efgh ijkl mnop"})
    assert response.status_code == 200
    assert response.json() == {"status": "enrolment_required"}
    assert response.cookies.get(sessions.COOKIE)

    user = await load_user("owner@example.com")
    assert (user.name, user.platform_role, user.totp_secret) == ("Olive Owner", "owner", None)
    assert await setup_row() is None
    status = await api.get("/api/auth/session")
    assert status.json() == {"status": "enrolment_required", "user": None}

    assert await actions() == ["auth.owner_created"]
    (event,) = await events("auth.owner_created")
    assert (event.actor_id, event.actor_name) == (str(user.id), "Olive Owner")
    assert (event.target_type, event.target_id, event.target_name) == ("user", str(user.id), "owner@example.com")
    assert (event.auth_method, event.mfa, str(event.source_ip)) == ("password", False, "127.0.0.1")


async def test_a_second_setup_gets_409(api):
    await make_user()
    response = await api.post("/api/auth/setup", json=BODY)
    assert response.status_code == 409
    assert response.json() == {"detail": "setup_closed"}
    assert await actions() == []


async def test_two_setups_at_once_create_one_owner(api):
    await put_setup_code(CODE)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as other:
        first, second = await asyncio.gather(
            api.post("/api/auth/setup", json=BODY),
            other.post("/api/auth/setup", json={**BODY, "email": "other@example.com"}),
        )
    assert {first.status_code, second.status_code} == {200, 409}
    assert await actions() == ["auth.owner_created"]


async def test_a_short_password_gets_422(api):
    await put_setup_code(CODE)
    response = await api.post("/api/auth/setup", json={**BODY, "password": "x" * 11})
    assert response.status_code == 422
    response = await api.post("/api/auth/setup", json={**BODY, "name": "   "})
    assert response.status_code == 422
    assert (await setup_row()).failed_attempts == 0

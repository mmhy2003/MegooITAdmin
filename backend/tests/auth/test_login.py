from datetime import timedelta

import argon2
import pytest
from auth_helpers import EMAIL, PASSWORD, actions, events, load_user, make_user
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from starlette.requests import Request as StarletteRequest

from app.audit import Actor, AuditEvent, Source
from app.auth import passwords, sessions
from app.auth.models import AuthSession, User
from app.auth.passwords import verify_password
from app.auth.service import auth_event
from app.core.db import SessionLocal
from app.main import create_app

WRONG = "not the right password at all"


def login(api, email=EMAIL, password=PASSWORD):
    return api.post("/api/auth/login", json={"email": email, "password": password})


def set_cookie_parts(response) -> set[str]:
    (header,) = response.headers.get_list("set-cookie")
    return {part.strip().lower() for part in header.split(";")}


async def session_rows() -> list[AuthSession]:
    async with SessionLocal() as db:
        return list((await db.scalars(select(AuthSession))).all())


async def test_the_right_password_gives_a_pending_session_and_mfa_required(api):
    user, _ = await make_user()
    response = await login(api)
    assert response.status_code == 200
    assert response.json() == {"status": "mfa_required"}
    token = response.cookies.get(sessions.COOKIE)
    assert token
    (row,) = await session_rows()
    assert (row.user_id, row.stage, row.mfa_method) == (user.id, "pending", None)
    assert row.token_hash == sessions.hash_token(token)
    assert (await api.get("/api/auth/session")).json() == {"status": "mfa_required", "user": None}

    assert await actions() == ["auth.password_accepted"]
    (event,) = await events("auth.password_accepted")
    assert (event.actor_id, event.actor_name, event.result) == (str(user.id), user.name, "success")
    assert (event.target_type, event.target_id) == ("user", str(user.id))
    assert (event.auth_method, event.mfa, str(event.source_ip)) == ("password", False, "127.0.0.1")


async def test_an_account_without_an_authenticator_gets_enrolment_required(api):
    await make_user(enrolled=False)
    response = await login(api)
    assert response.status_code == 200
    assert response.json() == {"status": "enrolment_required"}
    assert (await api.get("/api/auth/session")).json() == {"status": "enrolment_required", "user": None}


async def test_the_email_is_case_insensitive(api):
    await make_user()
    response = await login(api, email="  Owner@EXAMPLE.com ")
    assert response.status_code == 200
    assert response.json() == {"status": "mfa_required"}


async def test_a_wrong_password_and_an_unknown_email_get_the_same_answer(api, monkeypatch):
    user, _ = await make_user()
    dummy_calls = []
    real_dummy = passwords.verify_dummy

    async def spy(password: str) -> None:
        dummy_calls.append(password)
        await real_dummy(password)

    monkeypatch.setattr(passwords, "verify_dummy", spy)

    wrong = await login(api, password=WRONG)
    unknown = await login(api, email="Nobody@Example.com", password=WRONG)
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "invalid_credentials"}
    assert sessions.COOKIE not in wrong.cookies and sessions.COOKIE not in unknown.cookies
    assert dummy_calls == [WRONG]

    first, second = await events("auth.sign_in_failed")
    assert (first.actor_id, first.result, first.result_detail) == (str(user.id), "failure", {"reason": "wrong_password"})
    assert (second.actor_type, second.actor_id, second.actor_name) == ("human", None, "Nobody@Example.com")
    assert (second.target_id, second.result, second.result_detail) == (None, "failure", {"reason": "unknown_account"})
    assert await session_rows() == []


async def test_an_unknown_email_is_cut_to_254_characters_in_the_event(api):
    email = "a" * 300 + "@example.com"
    response = await login(api, email=email)
    assert response.status_code == 401
    (event,) = await events("auth.sign_in_failed")
    assert event.actor_name == email[:254]


async def test_five_wrong_passwords_lock_the_account(api, clock):
    user, _ = await make_user()
    for attempt in range(1, 5):
        assert (await login(api, password=WRONG)).json() == {"detail": "invalid_credentials"}
        assert (await load_user()).failed_attempts == attempt
    assert await events("auth.account_locked") == []

    response = await login(api, password=WRONG)
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_credentials"}
    locked = await load_user()
    assert locked.locked_until == clock.now + timedelta(minutes=15)
    assert locked.failed_attempts == 0
    assert len(await events("auth.sign_in_failed")) == 5
    (event,) = await events("auth.account_locked")
    assert (event.actor_id, event.target_type, event.target_id) == (str(user.id), "user", str(user.id))
    assert await actions() == ["auth.sign_in_failed"] * 5 + ["auth.account_locked"]


async def test_a_locked_account_refuses_the_right_password_with_the_same_message(api, clock):
    await make_user()
    for _ in range(5):
        await login(api, password=WRONG)
    clock.advance(minutes=14, seconds=59)

    response = await login(api)
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_credentials"}
    assert sessions.COOKIE not in response.cookies
    assert (await events("auth.sign_in_failed"))[-1].result_detail == {"reason": "locked"}
    assert await events("auth.password_accepted") == []
    assert await session_rows() == []


async def test_the_lock_ends_after_15_minutes_and_the_counter_starts_at_0(api, clock):
    await make_user()
    for _ in range(5):
        await login(api, password=WRONG)
    clock.advance(minutes=15)

    response = await login(api, password=WRONG)
    assert response.json() == {"detail": "invalid_credentials"}
    after = await load_user()
    assert (after.locked_until, after.failed_attempts) == (None, 1)
    assert (await events("auth.sign_in_failed"))[-1].result_detail == {"reason": "wrong_password"}
    assert (await login(api)).status_code == 200


async def test_a_right_password_does_not_reset_the_counter(api):
    await make_user()
    for _ in range(3):
        await login(api, password=WRONG)
    assert (await login(api)).status_code == 200
    assert (await load_user()).failed_attempts == 3


async def test_an_old_hash_is_rehashed_at_sign_in(api):
    user, _ = await make_user()
    old = argon2.PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
    async with SessionLocal() as db:
        await db.execute(update(User).where(User.id == user.id).values(password_hash=old))
        await db.commit()

    assert (await login(api)).status_code == 200
    new = (await load_user()).password_hash
    assert new != old
    assert not passwords.needs_rehash(new)
    assert await verify_password(new, PASSWORD)


async def test_expired_sessions_of_the_user_are_deleted_at_sign_in(api, clock):
    user, _ = await make_user()
    other, _ = await make_user(email="other@example.com")
    async with SessionLocal() as db:
        await sessions.create_session(db, user, Source(), stage="active", mfa_method="totp")
        await sessions.create_session(db, other, Source(), stage="active", mfa_method="totp")
        await db.commit()
    clock.advance(hours=2)

    assert (await login(api)).status_code == 200
    rows = await session_rows()
    assert sorted((row.user_id == user.id, row.stage) for row in rows) == [(False, "active"), (True, "pending")]


async def test_the_cookie_is_not_secure_over_http(api):
    await make_user()
    response = await login(api)
    parts = set_cookie_parts(response)
    assert {"httponly", "samesite=lax", "path=/"} <= parts
    assert "secure" not in parts


async def test_the_cookie_is_secure_over_https(clean_auth, clock):
    await make_user()
    transport = ASGITransport(app=create_app(), client=("127.0.0.1", 50000))
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        response = await login(client)
    assert response.status_code == 200
    assert {"httponly", "samesite=lax", "secure"} <= set_cookie_parts(response)


@pytest.mark.parametrize("password", [PASSWORD, WRONG])
async def test_no_event_holds_the_password(api, password):
    await make_user()
    await login(api, password=password)
    await login(api, email="nobody@example.com", password=password)
    async with SessionLocal() as db:
        rows = (await db.scalars(select(AuditEvent))).all()
    assert len(rows) == 2
    for row in rows:
        values = " ".join(repr(getattr(row, column.key)) for column in AuditEvent.__table__.columns)
        assert password not in values


async def test_a_disabled_account_is_refused_with_the_usual_message(api):
    user, _ = await make_user(disabled=True)

    response = await login(api)

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_credentials"}
    assert sessions.COOKIE not in response.cookies
    (event,) = await events("auth.sign_in_failed")
    assert (event.actor_id, event.target_type, event.target_id) == (str(user.id), "user", str(user.id))
    assert (event.result, event.result_detail) == ("failure", {"reason": "disabled"})
    assert (await load_user()).failed_attempts == 0
    assert await session_rows() == []


async def test_an_account_that_has_not_accepted_its_invite_is_refused(api):
    user, _ = await make_user(password=None, enrolled=False)

    response = await login(api)

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_credentials"}
    (event,) = await events("auth.sign_in_failed")
    assert (event.actor_id, event.target_id) == (str(user.id), str(user.id))
    assert (event.result, event.result_detail) == ("failure", {"reason": "not_accepted"})
    assert (await load_user()).failed_attempts == 0
    assert await session_rows() == []


def test_auth_event_carries_the_change_and_the_context():
    request = StarletteRequest({"type": "http", "method": "GET", "path": "/", "headers": [], "client": None})
    change = {"role": {"before": "operator", "after": "admin"}}

    event = auth_event(
        request, "user.role_changed", Actor.system("test"), mfa=True, change=change, context={"group": "staging"}
    )

    assert (event.change, event.context) == (change, {"group": "staging"})
    assert auth_event(request, "user.role_changed", Actor.system("test"), mfa=True).context == {}

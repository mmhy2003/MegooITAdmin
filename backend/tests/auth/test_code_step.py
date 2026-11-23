from datetime import timedelta

import pyotp
from auth_helpers import PASSWORD, actions, code_for, events, load_user, make_user, sign_in
from conftest import owner_session
from sqlalchemy import func, select, text, update

from app.auth import recovery, sessions
from app.auth.models import AuthSession, RecoveryCode, User
from app.core.db import SessionLocal

WRONG = "not the right password at all"


def login(api, password=PASSWORD):
    return api.post("/api/auth/login", json={"email": "owner@example.com", "password": password})


def mfa(api, code, method="totp"):
    return api.post("/api/auth/login/mfa", json={"code": code, "method": method})


def wrong_code_for(secret: str, at) -> str:
    """A 6-digit code that matches none of the steps the check accepts at `at`."""
    totp = pyotp.TOTP(secret)
    accepted = {totp.at(at + timedelta(seconds=drift)) for drift in (-30, 0, 30)}
    return next(code for code in (f"{n:06d}" for n in range(1000)) if code not in accepted)


async def session_rows() -> list[AuthSession]:
    async with SessionLocal() as db:
        return list((await db.scalars(select(AuthSession))).all())


async def test_password_then_code_gives_an_active_session_under_a_new_token(api, clock):
    user, secret = await make_user()
    assert (await login(api)).status_code == 200
    pending_token = api.cookies.get(sessions.COOKIE)

    response = await mfa(api, code_for(secret, clock.now))
    assert response.status_code == 200
    assert response.json() == {"status": "active"}
    active_token = response.cookies.get(sessions.COOKIE)
    assert active_token and active_token != pending_token
    (row,) = await session_rows()
    assert (row.user_id, row.stage, row.mfa_method) == (user.id, "active", "totp")
    assert row.token_hash == sessions.hash_token(active_token)
    session = (await api.get("/api/auth/session")).json()
    assert session["status"] == "active" and session["user"]["email"] == user.email

    assert await actions() == ["auth.password_accepted", "auth.mfa_used", "auth.sign_in"]
    (used,) = await events("auth.mfa_used")
    assert (used.actor_id, used.target_id, used.result) == (str(user.id), str(user.id), "success")
    assert (used.result_detail, used.mfa) == ({"method": "totp"}, True)
    (signed_in,) = await events("auth.sign_in")
    assert (signed_in.actor_id, signed_in.mfa, signed_in.auth_method) == (str(user.id), True, "password")


async def test_a_code_cannot_be_used_twice(api, clock):
    _, secret = await make_user()
    code = code_for(secret, clock.now)
    await login(api)
    assert (await mfa(api, code)).status_code == 200

    await login(api)
    response = await mfa(api, code)
    assert response.status_code == 401
    assert response.json() == {"detail": "wrong_code"}


async def test_a_wrong_code_is_refused_and_counted(api, clock):
    user, secret = await make_user()
    await login(api)
    response = await mfa(api, wrong_code_for(secret, clock.now))
    assert response.status_code == 401
    assert response.json() == {"detail": "wrong_code"}
    assert sessions.COOKIE not in response.cookies
    assert (await load_user()).failed_attempts == 1
    (row,) = await session_rows()
    assert row.stage == "pending"
    (event,) = await events("auth.mfa_failed")
    assert (event.actor_id, event.target_id, event.result) == (str(user.id), str(user.id), "failure")
    assert (event.result_detail, event.mfa) == ({"reason": "wrong_code", "method": "totp"}, False)


async def test_wrong_passwords_and_codes_share_the_counter(api, clock):
    _, secret = await make_user()
    for _ in range(3):
        await login(api, password=WRONG)
    await login(api)
    wrong = wrong_code_for(secret, clock.now)
    assert (await mfa(api, wrong)).json() == {"detail": "wrong_code"}
    response = await mfa(api, wrong)
    assert response.status_code == 401
    assert response.json() == {"detail": "locked"}
    assert (await load_user()).locked_until == clock.now + timedelta(minutes=15)
    assert len(await events("auth.account_locked")) == 1


async def test_a_success_resets_the_counter(api, clock):
    _, secret = await make_user()
    for _ in range(3):
        await login(api, password=WRONG)
    await login(api)
    await mfa(api, wrong_code_for(secret, clock.now))
    assert (await load_user()).failed_attempts == 4
    assert (await mfa(api, code_for(secret, clock.now))).status_code == 200
    assert (await load_user()).failed_attempts == 0


async def test_a_recovery_code_signs_in_once(api, clock):
    code = recovery.new_code()
    user, _ = await make_user(recovery_codes=[code, recovery.new_code()])
    await login(api)
    response = await mfa(api, code.lower(), method="recovery_code")
    assert response.status_code == 200
    assert response.json() == {"status": "active"}
    (row,) = await session_rows()
    assert (row.stage, row.mfa_method) == ("active", "recovery_code")
    async with SessionLocal() as db:
        hashes = set((await db.scalars(select(RecoveryCode.code_hash))).all())
    assert len(hashes) == 1 and recovery.hash_code(code) not in hashes
    (used,) = await events("auth.mfa_used")
    assert used.result_detail == {"method": "recovery_code"}

    await login(api)
    again = await mfa(api, code, method="recovery_code")
    assert again.status_code == 401
    assert again.json() == {"detail": "wrong_code"}
    assert (await events("auth.mfa_failed"))[-1].result_detail == {"reason": "wrong_code", "method": "recovery_code"}


async def test_a_locked_account_cannot_finish_the_sign_in(api, clock):
    user, secret = await make_user()
    await login(api)
    async with SessionLocal() as db:
        await db.execute(update(User).where(User.id == user.id).values(locked_until=clock.now + timedelta(minutes=5)))
        await db.commit()

    response = await mfa(api, code_for(secret, clock.now))
    assert response.status_code == 401
    assert response.json() == {"detail": "locked"}
    assert sessions.COOKIE not in response.cookies
    assert [row.stage for row in await session_rows()] == ["pending"]
    (event,) = await events("auth.mfa_failed")
    assert event.result_detail == {"reason": "locked", "method": "totp"}
    assert await events("auth.sign_in") == []


async def test_an_undecryptable_secret_is_refused_without_counting(api, clock):
    user, secret = await make_user()
    async with owner_session() as db:
        await db.execute(text("UPDATE users SET totp_secret = :blob"), {"blob": b"garbage"})
        await db.commit()
    await login(api)

    response = await mfa(api, code_for(secret, clock.now))
    assert response.status_code == 401
    assert response.json() == {"detail": "undecryptable"}
    assert (await load_user()).failed_attempts == 0
    (event,) = await events("auth.mfa_failed")
    assert event.result_detail == {"reason": "undecryptable", "method": "totp"}


async def test_an_unenrolled_account_gets_409(api, clock):
    await make_user(enrolled=False)
    assert (await login(api)).json() == {"status": "enrolment_required"}
    response = await mfa(api, "123456")
    assert response.status_code == 409
    assert response.json() == {"detail": "not_enrolled"}
    assert await actions() == ["auth.password_accepted"]


async def test_an_active_session_gets_409(api, clock):
    _, secret = await make_user()
    await sign_in(api, clock, secret)
    response = await mfa(api, code_for(secret, clock.now))
    assert response.status_code == 409
    assert response.json() == {"detail": "already_signed_in"}
    assert len(await events("auth.mfa_used")) == 1
    assert [row.stage for row in await session_rows()] == ["active"]


async def test_after_ten_minutes_the_code_step_answers_not_signed_in(api, clock):
    _, secret = await make_user()
    await login(api)
    clock.advance(minutes=10)
    response = await mfa(api, code_for(secret, clock.now))
    assert response.status_code == 401
    assert response.json() == {"detail": "not_signed_in"}
    async with SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(AuthSession)) == 0
    assert (await events("auth.mfa_failed"))[-1].result_detail == {"reason": "expired"}

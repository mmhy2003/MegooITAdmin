import re
from datetime import timedelta

import pyotp
from auth_helpers import PASSWORD, actions, code_for, events, load_user, make_user, sign_in
from httpx import AsyncClient
from sqlalchemy import select

from app.auth import recovery, sessions
from app.auth.models import AuthSession, RecoveryCode
from app.core.db import SessionLocal

NEW_PASSWORD = "a brand new and long passphrase"


def change(api, current=PASSWORD, new=NEW_PASSWORD):
    return api.post("/api/auth/password", json={"current_password": current, "new_password": new})


def new_codes(api, code):
    return api.post("/api/auth/recovery-codes", json={"code": code})


def wrong_code_for(secret: str, at) -> str:
    """A 6-digit code that matches none of the steps the check accepts at `at`."""
    accepted = {pyotp.TOTP(secret).at(at + timedelta(seconds=drift)) for drift in (-30, 0, 30)}
    return next(code for code in (f"{n:06d}" for n in range(1000)) if code not in accepted)


def other_client(api) -> AsyncClient:
    """A second browser on the same app."""
    return AsyncClient(transport=api._transport, base_url="http://test")


async def session_rows() -> list[AuthSession]:
    async with SessionLocal() as db:
        return list((await db.scalars(select(AuthSession))).all())


async def recovery_hashes() -> set[bytes]:
    async with SessionLocal() as db:
        return set((await db.scalars(select(RecoveryCode.code_hash))).all())


async def test_a_wrong_current_password_is_refused_and_counted(api, clock):
    user, secret = await make_user()
    await sign_in(api, clock, secret)

    response = await change(api, current="not the password at all")
    assert response.status_code == 401
    assert response.json() == {"detail": "wrong_password"}
    stored = await load_user()
    assert stored.failed_attempts == 1
    assert stored.password_hash == user.password_hash
    (event,) = await events("auth.password_changed")
    assert (event.actor_id, event.target_id, event.result, event.mfa) == (str(user.id), str(user.id), "failure", True)
    assert event.result_detail == {"reason": "wrong_password"}


async def test_a_password_change_ends_the_other_sessions_and_keeps_this_one(api, clock):
    user, secret = await make_user()
    await sign_in(api, clock, secret)
    async with other_client(api) as other:
        await sign_in(other, clock, secret)
        other_hash = sessions.hash_token(other.cookies.get(sessions.COOKIE))
        (other_row,) = [row for row in await session_rows() if row.token_hash == other_hash]
        clock.advance(minutes=5)

        response = await change(api)
        assert response.status_code == 200
        assert response.json() == {"status": "active"}

        (row,) = await session_rows()
        assert row.token_hash == sessions.hash_token(api.cookies.get(sessions.COOKIE))
        assert (await api.get("/api/auth/session")).json()["status"] == "active"
        assert (await other.get("/api/auth/session")).json()["status"] == "signed_out"

    stored = await load_user()
    assert stored.password_changed_at == clock.now
    assert (await actions())[-2:] == ["auth.password_changed", "auth.session_revoked"]
    (changed,) = await events("auth.password_changed")
    assert (changed.actor_id, changed.target_id, changed.result, changed.mfa) == (
        str(user.id),
        str(user.id),
        "success",
        True,
    )
    (revoked,) = await events("auth.session_revoked")
    assert (revoked.actor_id, revoked.target_type, revoked.target_id) == (
        str(user.id),
        "auth_session",
        str(other_row.id),
    )


async def test_the_new_password_signs_in_and_the_old_does_not(api, clock):
    _, secret = await make_user()
    await sign_in(api, clock, secret)
    assert (await change(api)).status_code == 200
    await api.post("/api/auth/logout")

    old = await api.post("/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
    assert old.status_code == 401
    assert old.json() == {"detail": "invalid_credentials"}
    await sign_in(api, clock, secret, password=NEW_PASSWORD)
    assert (await api.get("/api/auth/session")).json()["status"] == "active"


async def test_a_short_new_password_gets_422(api, clock):
    user, secret = await make_user()
    await sign_in(api, clock, secret)

    response = await change(api, new="too short")
    assert response.status_code == 422
    assert (await load_user()).password_hash == user.password_hash
    assert await events("auth.password_changed") == []


async def test_new_recovery_codes_replace_the_old_ones(api, clock):
    old_code = recovery.new_code()
    user, secret = await make_user(recovery_codes=[old_code])
    await sign_in(api, clock, secret)

    response = await new_codes(api, code_for(secret, clock.now))
    assert response.status_code == 200
    codes = response.json()["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    assert all(re.fullmatch(recovery.CODE_PATTERN, code) for code in codes)
    assert await recovery_hashes() == {recovery.hash_code(code) for code in codes}
    (event,) = await events("auth.recovery_codes_created")
    assert (event.actor_id, event.target_id, event.result, event.mfa) == (str(user.id), str(user.id), "success", True)
    assert event.result_detail == {"count": 10}

    await api.post("/api/auth/logout")
    async with other_client(api) as browser:
        await browser.post("/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
        refused = await browser.post("/api/auth/login/mfa", json={"code": old_code, "method": "recovery_code"})
        assert refused.json() == {"detail": "wrong_code"}
        accepted = await browser.post("/api/auth/login/mfa", json={"code": codes[0], "method": "recovery_code"})
        assert accepted.status_code == 200
        assert accepted.json() == {"status": "active"}


async def test_new_recovery_codes_need_a_current_code(api, clock):
    old_code = recovery.new_code()
    user, secret = await make_user(recovery_codes=[old_code])
    await sign_in(api, clock, secret)

    missing = await api.post("/api/auth/recovery-codes", json={})
    assert missing.status_code == 422

    response = await new_codes(api, wrong_code_for(secret, clock.now))
    assert response.status_code == 401
    assert response.json() == {"detail": "wrong_code"}
    assert await recovery_hashes() == {recovery.hash_code(old_code)}
    assert (await load_user()).failed_attempts == 1
    (event,) = await events("auth.mfa_failed")
    assert (event.actor_id, event.result, event.mfa) == (str(user.id), "failure", True)
    assert event.result_detail == {"reason": "wrong_code", "method": "totp"}
    assert await events("auth.recovery_codes_created") == []


async def test_five_failures_on_the_profile_lock_the_account_and_open_sessions_stay(api, clock):
    _, secret = await make_user()
    await sign_in(api, clock, secret)

    for _ in range(2):
        assert (await change(api, current="not the password at all")).json() == {"detail": "wrong_password"}
    for _ in range(2):
        assert (await new_codes(api, wrong_code_for(secret, clock.now))).json() == {"detail": "wrong_code"}
    fifth = await change(api, current="not the password at all")
    assert fifth.status_code == 401
    assert fifth.json() == {"detail": "locked"}

    assert len(await events("auth.account_locked")) == 1
    assert (await load_user()).locked_until == clock.now + timedelta(minutes=15)
    assert (await api.get("/api/auth/me")).status_code == 200

    # While locked, even the right proof is refused, and the refusals are recorded.
    locked = await change(api)
    assert locked.json() == {"detail": "locked"}
    assert (await events("auth.password_changed"))[-1].result_detail == {"reason": "locked"}
    locked = await new_codes(api, code_for(secret, clock.now))
    assert locked.json() == {"detail": "locked"}
    assert (await events("auth.mfa_failed"))[-1].result_detail == {"reason": "locked", "method": "totp"}
    assert (await api.get("/api/auth/me")).status_code == 200

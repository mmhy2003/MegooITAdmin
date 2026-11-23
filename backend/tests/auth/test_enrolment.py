import re
from datetime import timedelta

import pyotp
from auth_helpers import PASSWORD, actions, code_for, events, load_user, make_user, sign_in
from httpx import AsyncClient
from sqlalchemy import select

from app.auth import recovery, sessions, totp
from app.auth.crypto import decrypt_secret
from app.auth.models import AuthSession, RecoveryCode
from app.core.config import get_settings
from app.core.db import SessionLocal


def login(api):
    return api.post("/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD})


def enrol(api, code=None, method="totp"):
    body = {} if code is None else {"code": code, "method": method}
    return api.post("/api/auth/mfa/enrol", json=body)


def confirm(api, code):
    return api.post("/api/auth/mfa/enrol/confirm", json={"code": code})


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


def plain_secret(user, blob: bytes) -> str:
    return decrypt_secret(get_settings().auth_key(), user.id, blob)


async def test_an_account_without_an_authenticator_enrols_and_gets_ten_codes(api, clock):
    user, _ = await make_user(enrolled=False)
    assert (await login(api)).json() == {"status": "enrolment_required"}
    pending_token = api.cookies.get(sessions.COOKIE)

    started = await enrol(api)
    assert started.status_code == 200
    secret = started.json()["secret"]
    assert started.json()["uri"] == totp.provisioning_uri(secret, user.email)

    response = await confirm(api, code_for(secret, clock.now))
    assert response.status_code == 200
    codes = response.json()["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    assert all(re.fullmatch(recovery.CODE_PATTERN, code) for code in codes)
    assert await recovery_hashes() == {recovery.hash_code(code) for code in codes}

    active_token = response.cookies.get(sessions.COOKIE)
    assert active_token and active_token != pending_token
    (row,) = await session_rows()
    assert (row.stage, row.mfa_method, row.token_hash) == ("active", "totp", sessions.hash_token(active_token))
    assert (await api.get("/api/auth/session")).json()["status"] == "active"

    stored = await load_user()
    assert plain_secret(stored, stored.totp_secret) == secret
    assert stored.totp_pending_secret is None
    assert stored.totp_confirmed_at == clock.now
    assert stored.totp_last_step == int(clock.now.timestamp()) // totp.PERIOD
    assert await actions() == [
        "auth.password_accepted",
        "auth.mfa_enrolment_started",
        "auth.mfa_enrolled",
        "auth.sign_in",
    ]
    (enrolled,) = await events("auth.mfa_enrolled")
    assert (enrolled.actor_id, enrolled.target_id, enrolled.result) == (str(user.id), str(user.id), "success")


async def test_the_pending_secret_is_stored_encrypted(api, clock):
    await make_user(enrolled=False)
    await login(api)
    secret = (await enrol(api)).json()["secret"]

    stored = await load_user()
    assert stored.totp_secret is None
    assert secret.encode() not in stored.totp_pending_secret
    assert plain_secret(stored, stored.totp_pending_secret) == secret
    for event in await events("auth.mfa_enrolment_started"):
        assert secret not in str(event.result_detail)


async def test_a_wrong_confirmation_code_is_refused_and_counted(api, clock):
    user, _ = await make_user(enrolled=False)
    await login(api)
    secret = (await enrol(api)).json()["secret"]

    response = await confirm(api, wrong_code_for(secret, clock.now))
    assert response.status_code == 401
    assert response.json() == {"detail": "wrong_code"}
    assert sessions.COOKIE not in response.cookies
    stored = await load_user()
    assert stored.failed_attempts == 1
    assert stored.totp_secret is None and stored.totp_pending_secret is not None
    assert [row.stage for row in await session_rows()] == ["pending"]
    assert await recovery_hashes() == set()
    (event,) = await events("auth.mfa_failed")
    assert (event.actor_id, event.result, event.mfa) == (str(user.id), "failure", False)
    assert event.result_detail == {"reason": "wrong_code"}


async def test_an_enrolled_pending_session_gets_409(api, clock):
    await make_user()
    await login(api)
    response = await enrol(api)
    assert response.status_code == 409
    assert response.json() == {"detail": "already_enrolled"}
    assert (await load_user()).totp_pending_secret is None
    assert await actions() == ["auth.password_accepted"]


async def test_an_enrolled_pending_session_cannot_confirm_a_replacement_started_elsewhere(api, clock):
    code = recovery.new_code()
    _, secret = await make_user(recovery_codes=[code])
    await sign_in(api, clock, secret)
    new_secret = (await enrol(api, code_for(secret, clock.now))).json()["secret"]

    async with other_client(api) as other:
        assert (await login(other)).json() == {"status": "mfa_required"}
        response = await confirm(other, code_for(new_secret, clock.now))
        assert response.status_code == 409
        assert response.json() == {"detail": "already_enrolled"}
        assert sessions.COOKIE not in response.cookies
        assert (await other.get("/api/auth/session")).json()["status"] == "mfa_required"

    stored = await load_user()
    assert plain_secret(stored, stored.totp_secret) == secret
    assert plain_secret(stored, stored.totp_pending_secret) == new_secret
    assert await recovery_hashes() == {recovery.hash_code(code)}
    assert await events("auth.mfa_enrolled") == []


async def test_replacing_needs_a_current_code(api, clock):
    user, secret = await make_user()
    await sign_in(api, clock, secret)

    response = await enrol(api)
    assert response.status_code == 422
    assert response.json() == {"detail": "code_required"}

    response = await enrol(api, wrong_code_for(secret, clock.now))
    assert response.status_code == 401
    assert response.json() == {"detail": "wrong_code"}
    stored = await load_user()
    assert stored.failed_attempts == 1
    assert stored.totp_pending_secret is None
    (event,) = await events("auth.mfa_failed")
    assert (event.actor_id, event.mfa) == (str(user.id), True)
    assert event.result_detail == {"reason": "wrong_code", "method": "totp"}
    assert await events("auth.mfa_enrolment_started") == []


async def test_replacing_with_a_recovery_code_uses_it_up(api, clock):
    code = recovery.new_code()
    _, secret = await make_user(recovery_codes=[code])
    await sign_in(api, clock, secret)

    response = await enrol(api, code, method="recovery_code")
    assert response.status_code == 200
    assert await recovery_hashes() == set()
    assert (await load_user()).totp_pending_secret is not None
    (started,) = await events("auth.mfa_enrolment_started")
    assert started.mfa is True

    again = await enrol(api, code, method="recovery_code")
    assert again.status_code == 401
    assert again.json() == {"detail": "wrong_code"}


async def test_replacing_ends_the_other_sessions_and_keeps_this_one(api, clock):
    kept_code = recovery.new_code()
    user, secret = await make_user(recovery_codes=[kept_code])
    await sign_in(api, clock, secret)
    async with other_client(api) as other:
        await sign_in(other, clock, secret)
        other_hash = sessions.hash_token(other.cookies.get(sessions.COOKIE))
        (other_row,) = [row for row in await session_rows() if row.token_hash == other_hash]

        new_secret = (await enrol(api, code_for(secret, clock.now))).json()["secret"]
        response = await confirm(api, code_for(new_secret, clock.now))
        assert response.status_code == 200
        assert response.json() == {"recovery_codes": None}
        assert sessions.COOKIE not in response.cookies

        (row,) = await session_rows()
        assert row.token_hash == sessions.hash_token(api.cookies.get(sessions.COOKIE))
        assert (await api.get("/api/auth/session")).json()["status"] == "active"
        assert (await other.get("/api/auth/session")).json()["status"] == "signed_out"

    stored = await load_user()
    assert plain_secret(stored, stored.totp_secret) == new_secret
    assert stored.totp_pending_secret is None
    assert await recovery_hashes() == {recovery.hash_code(kept_code)}
    assert (await actions())[-2:] == ["auth.mfa_enrolled", "auth.session_revoked"]
    (enrolled,) = await events("auth.mfa_enrolled")
    assert enrolled.mfa is True
    (revoked,) = await events("auth.session_revoked")
    assert (revoked.actor_id, revoked.target_type, revoked.target_id) == (
        str(user.id),
        "auth_session",
        str(other_row.id),
    )


async def test_after_replacing_the_old_secret_no_longer_signs_in(api, clock):
    _, old_secret = await make_user()
    await sign_in(api, clock, old_secret)
    new_secret = (await enrol(api, code_for(old_secret, clock.now))).json()["secret"]
    assert (await confirm(api, code_for(new_secret, clock.now))).status_code == 200
    clock.advance(seconds=30)

    async with other_client(api) as other:
        await login(other)
        refused = await other.post("/api/auth/login/mfa", json={"code": code_for(old_secret, clock.now)})
        assert refused.status_code == 401
        assert refused.json() == {"detail": "wrong_code"}
        accepted = await other.post("/api/auth/login/mfa", json={"code": code_for(new_secret, clock.now)})
        assert accepted.status_code == 200


async def test_confirm_without_a_started_enrolment_gets_409(api, clock):
    await make_user(enrolled=False)
    await login(api)
    response = await confirm(api, "123456")
    assert response.status_code == 409
    assert response.json() == {"detail": "no_enrolment"}
    assert await actions() == ["auth.password_accepted"]

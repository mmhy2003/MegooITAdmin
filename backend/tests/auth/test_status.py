from auth_helpers import EMAIL, NAME, make_user

from app.audit import Source
from app.auth import sessions
from app.core.db import SessionLocal


async def start(user, stage: str) -> str:
    async with SessionLocal() as db:
        token = await sessions.create_session(
            db, user, Source(), stage=stage, mfa_method="totp" if stage == "active" else None
        )
        await db.commit()
    return token


async def status(api, token: str | None = None):
    headers = {"cookie": f"{sessions.COOKIE}={token}"} if token else {}
    response = await api.get("/api/auth/session", headers=headers)
    assert response.status_code == 200
    return response.json()


async def test_without_an_account_setup_is_required(api):
    assert await status(api) == {"status": "setup_required", "user": None}


async def test_without_a_session_it_is_signed_out(api):
    await make_user()
    assert await status(api) == {"status": "signed_out", "user": None}
    assert await status(api, "made-up-token") == {"status": "signed_out", "user": None}


async def test_a_pending_session_of_an_enrolled_account_needs_its_code(api):
    user, _ = await make_user()
    assert await status(api, await start(user, "pending")) == {"status": "mfa_required", "user": None}


async def test_a_pending_session_of_an_account_without_an_authenticator_needs_enrolment(api):
    user, _ = await make_user(enrolled=False)
    assert await status(api, await start(user, "pending")) == {"status": "enrolment_required", "user": None}


async def test_an_active_session_is_active_with_its_user(api):
    user, _ = await make_user()
    assert await status(api, await start(user, "active")) == {
        "status": "active",
        "user": {"id": str(user.id), "name": NAME, "email": EMAIL, "platform_role": "owner"},
    }


async def test_an_expired_session_is_signed_out(api, clock):
    user, _ = await make_user()
    token = await start(user, "active")
    clock.advance(hours=1)
    assert await status(api, token) == {"status": "signed_out", "user": None}

import uuid
from datetime import datetime

from auth_helpers import actions, code_for, events, load_user, make_user, other_client, sign_in
from sqlalchemy import select, text, update

from app.auth import clock as auth_clock
from app.auth import sessions
from app.auth.models import User
from app.core.db import SessionLocal
from app.users.models import UserInvite

INVITEE = "ada@example.com"
NEW_PASSWORD = "a brand new passphrase"


async def owner(api, clock) -> User:
    """The Owner, signed in on `api`."""
    user, secret = await make_user()
    await sign_in(api, clock, secret)
    return user


async def invite(api) -> dict:
    """The Owner on `api` invites Ada. Returns the answer: user_id, token, expires_at."""
    body = {"name": "Ada Lovelace", "email": INVITEE, "platform_role": None, "grants": []}
    response = await api.post("/api/users", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def check(client, token):
    return client.post("/api/auth/invite/check", json={"token": token})


def accept(client, token, password=NEW_PASSWORD):
    return client.post("/api/auth/invite/accept", json={"token": token, "password": password})


async def invites() -> list[UserInvite]:
    async with SessionLocal() as session:
        return list((await session.scalars(select(UserInvite))).all())


async def disable(email: str) -> None:
    async with SessionLocal() as session:
        await session.execute(update(User).where(User.email == email).values(disabled_at=auth_clock.now()))
        await session.commit()


async def test_check_answers_the_name_and_email_of_a_valid_link(api, clock):
    await owner(api, clock)
    link = await invite(api)

    async with other_client(api) as browser:
        response = await check(browser, link["token"])

    assert (response.status_code, response.json()) == (200, {"name": "Ada Lovelace", "email": INVITEE})
    assert await events("user.invite_accepted") == []
    assert await events("user.invite_refused") == []


async def test_check_answers_404_for_an_unknown_expired_or_used_link(api, clock):
    await owner(api, clock)
    used = await invite(api)
    async with other_client(api) as browser:
        assert (await accept(browser, used["token"])).status_code == 200
        later = await api.post(
            "/api/users", json={"name": "Bo Later", "email": "bo@example.com", "platform_role": None, "grants": []}
        )
        expired = later.json()["token"]
        clock.advance(days=7, seconds=1)

        for token in ("not-a-token", used["token"], expired):
            response = await check(browser, token)
            assert (response.status_code, response.json()) == (404, {"detail": "invalid_invite"}), token


async def test_accept_sets_the_password_and_gives_a_pending_session_that_enrols(api, clock):
    await owner(api, clock)
    link = await invite(api)

    async with other_client(api) as browser:
        response = await accept(browser, link["token"])

        assert (response.status_code, response.json()) == (200, {"status": "enrolment_required"})
        assert response.cookies.get(sessions.COOKIE)
        assert (await browser.get("/api/auth/session")).json()["status"] == "enrolment_required"
        assert await invites() == []
        user = await load_user(INVITEE)
        assert user.password_hash is not None and NEW_PASSWORD not in user.password_hash
        assert user.password_changed_at == clock.now
        (accepted,) = await events("user.invite_accepted")
        assert (accepted.actor_id, accepted.target_id, accepted.result, accepted.mfa) == (
            link["user_id"],
            link["user_id"],
            "success",
            False,
        )

        started = await browser.post("/api/auth/mfa/enrol", json={})
        assert started.status_code == 200, started.text
        confirmed = await browser.post(
            "/api/auth/mfa/enrol/confirm", json={"code": code_for(started.json()["secret"], clock.now)}
        )
        assert confirmed.status_code == 200, confirmed.text
        assert (await browser.get("/api/auth/session")).json()["status"] == "active"

    # The password now signs in.
    async with other_client(api) as again:
        response = await again.post("/api/auth/login", json={"email": INVITEE, "password": NEW_PASSWORD})
        assert (response.status_code, response.json()) == (200, {"status": "mfa_required"})


async def test_a_link_works_once(api, clock):
    await owner(api, clock)
    link = await invite(api)

    async with other_client(api) as browser:
        assert (await accept(browser, link["token"])).status_code == 200
        second = await accept(browser, link["token"], password="another passphrase entirely")

    assert (second.status_code, second.json()) == (404, {"detail": "invalid_invite"})
    assert second.cookies.get(sessions.COOKIE) is None
    (refused,) = await events("user.invite_refused")
    assert (refused.actor_type, refused.actor_id, refused.actor_name) == ("human", None, "unknown")
    assert (refused.result, refused.result_detail) == ("failure", {"reason": "unknown"})


async def test_an_expired_link_is_refused_and_recorded(api, clock):
    await owner(api, clock)
    link = await invite(api)
    clock.advance(days=7, seconds=1)

    async with other_client(api) as browser:
        response = await accept(browser, link["token"])

    assert (response.status_code, response.json()) == (404, {"detail": "invalid_invite"})
    assert (await load_user(INVITEE)).password_hash is None
    (refused,) = await events("user.invite_refused")
    assert (refused.actor_id, refused.target_id) == (link["user_id"], link["user_id"])
    assert (refused.result, refused.result_detail) == ("failure", {"reason": "expired"})
    assert await events("user.invite_accepted") == []


async def test_a_replaced_link_is_refused(api, clock):
    the_owner = await owner(api, clock)
    old = await invite(api)

    renewed = await api.post(f"/api/users/{old['user_id']}/invite")

    assert renewed.status_code == 200, renewed.text
    new = renewed.json()
    assert new["user_id"] == old["user_id"] and new["token"] != old["token"]
    assert len(await invites()) == 1
    (event,) = await events("user.invite_renewed")
    assert (event.actor_id, event.target_id, event.mfa) == (str(the_owner.id), old["user_id"], True)
    assert datetime.fromisoformat(event.result_detail["expires_at"]) == datetime.fromisoformat(new["expires_at"])
    async with other_client(api) as browser:
        stale = await accept(browser, old["token"])
        assert (stale.status_code, stale.json()) == (404, {"detail": "invalid_invite"})
        assert (await accept(browser, new["token"])).status_code == 200


async def test_renewing_an_accepted_invite_gets_409_already_accepted(api, clock):
    await owner(api, clock)
    link = await invite(api)
    async with other_client(api) as browser:
        assert (await accept(browser, link["token"])).status_code == 200

    response = await api.post(f"/api/users/{link['user_id']}/invite")

    assert (response.status_code, response.json()) == (409, {"detail": "already_accepted"})
    assert await invites() == []
    assert await events("user.invite_renewed") == []


async def test_renewing_an_unknown_account_gets_404(api, clock):
    await owner(api, clock)

    response = await api.post(f"/api/users/{uuid.uuid4()}/invite")

    assert (response.status_code, response.json()) == (404, {"detail": "not_found"})
    assert await invites() == []


async def test_a_disabled_accounts_link_is_refused(api, clock):
    await owner(api, clock)
    link = await invite(api)
    await disable(INVITEE)

    async with other_client(api) as browser:
        checked = await check(browser, link["token"])
        response = await accept(browser, link["token"])

    assert (checked.status_code, checked.json()) == (404, {"detail": "invalid_invite"})
    assert (response.status_code, response.json()) == (404, {"detail": "invalid_invite"})
    assert (await load_user(INVITEE)).password_hash is None
    (refused,) = await events("user.invite_refused")
    assert (refused.actor_id, refused.target_id) == (link["user_id"], link["user_id"])
    assert refused.result_detail == {"reason": "disabled"}


async def test_no_event_holds_the_token_or_the_password(api, clock):
    await owner(api, clock)
    first = await invite(api)
    renewed = (await api.post(f"/api/users/{first['user_id']}/invite")).json()
    async with other_client(api) as browser:
        await accept(browser, first["token"])
        await accept(browser, renewed["token"])
        await accept(browser, renewed["token"], password="the second try passphrase")

    async with SessionLocal() as session:
        rows = (await session.execute(text("SELECT to_jsonb(a)::text FROM audit_log a"))).scalars().all()
    assert {"user.invited", "user.invite_renewed", "user.invite_accepted", "user.invite_refused"} <= set(await actions())
    for secret in (first["token"], renewed["token"], NEW_PASSWORD, "the second try passphrase"):
        assert not any(secret in row for row in rows), secret


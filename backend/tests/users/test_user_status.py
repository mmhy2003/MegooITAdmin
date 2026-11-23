from auth_helpers import PASSWORD, actions, add_grant, events, load_user, make_group, make_user, other_client, sign_in
from sqlalchemy import select

from app.access.models import RoleGrant
from app.auth.models import AuthSession, RecoveryCode, User
from app.core.db import SessionLocal
from app.users.models import UserInvite

PERSON = "pat@example.com"


async def owner(api, clock) -> User:
    """The Owner, signed in on `api`."""
    user, secret = await make_user()
    await sign_in(api, clock, secret)
    return user


async def login(client, email: str = PERSON):
    return await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})


async def sessions_of(user_id) -> list[AuthSession]:
    async with SessionLocal() as session:
        return list((await session.scalars(select(AuthSession).where(AuthSession.user_id == user_id))).all())


async def test_disable_ends_the_sessions_and_refuses_sign_in(api, clock):
    the_owner = await owner(api, clock)
    pat, pat_secret = await make_user(email=PERSON, name="Pat Person", platform_role=None)
    async with other_client(api) as pat_client:
        await sign_in(pat_client, clock, pat_secret, email=PERSON)
        (pat_session,) = await sessions_of(pat.id)

        response = await api.post(f"/api/users/{pat.id}/disable")

        assert response.status_code == 204, response.text
        assert (await pat_client.get("/api/auth/me")).status_code == 401
        refused = await login(pat_client)
        assert (refused.status_code, refused.json()) == (401, {"detail": "invalid_credentials"})

    assert (await load_user(PERSON)).disabled_at == clock.now
    assert await sessions_of(pat.id) == []
    (disabled,) = await events("user.disabled")
    assert (disabled.actor_id, disabled.target_type, disabled.target_id, disabled.target_name) == (
        str(the_owner.id),
        "user",
        str(pat.id),
        PERSON,
    )
    assert (disabled.result, disabled.mfa) == ("success", True)
    assert disabled.change == {"status": {"before": "active", "after": "disabled"}}
    (revoked,) = await events("auth.session_revoked")
    assert (revoked.actor_id, revoked.target_type, revoked.target_id) == (
        str(the_owner.id),
        "auth_session",
        str(pat_session.id),
    )
    (failed,) = await events("auth.sign_in_failed")
    assert failed.result_detail == {"reason": "disabled"}
    tail = await actions()
    assert tail[tail.index("user.disabled") :][:2] == ["user.disabled", "auth.session_revoked"]


async def test_disable_deletes_an_open_invite(api, clock):
    await owner(api, clock)
    invited = await api.post("/api/users", json={"email": PERSON, "name": "Pat Person", "platform_role": "auditor"})
    assert invited.status_code == 200, invited.text
    user_id = invited.json()["user_id"]

    response = await api.post(f"/api/users/{user_id}/disable")

    assert response.status_code == 204, response.text
    async with SessionLocal() as session:
        assert (await session.scalars(select(UserInvite))).all() == []
    (disabled,) = await events("user.disabled")
    assert disabled.change == {"status": {"before": "invited", "after": "disabled"}}
    check = await api.post("/api/auth/invite/check", json={"token": invited.json()["token"]})
    assert check.status_code == 404


async def test_disabling_twice_gets_409_no_change(api, clock):
    await owner(api, clock)
    pat, _ = await make_user(email=PERSON, name="Pat Person", platform_role=None, disabled=True)

    response = await api.post(f"/api/users/{pat.id}/disable")

    assert (response.status_code, response.json()) == (409, {"detail": "no_change"})
    assert await events("user.disabled") == []


async def test_enabling_an_enabled_account_gets_409_no_change(api, clock):
    await owner(api, clock)
    pat, _ = await make_user(email=PERSON, name="Pat Person", platform_role=None)

    response = await api.post(f"/api/users/{pat.id}/enable")

    assert (response.status_code, response.json()) == (409, {"detail": "no_change"})
    assert await events("user.enabled") == []


async def test_enable_restores_sign_in_with_the_same_roles(api, clock):
    the_owner = await owner(api, clock)
    pat, pat_secret = await make_user(email=PERSON, name="Pat Person", platform_role=None, disabled=True)
    staging = await make_group("staging")
    grant = await add_grant(pat.id, staging.id, "operator")

    response = await api.post(f"/api/users/{pat.id}/enable")

    assert response.status_code == 204, response.text
    assert (await load_user(PERSON)).disabled_at is None
    async with SessionLocal() as session:
        (kept,) = (await session.scalars(select(RoleGrant).where(RoleGrant.user_id == pat.id))).all()
        assert kept.fields() == grant.fields()
    (enabled,) = await events("user.enabled")
    assert (enabled.actor_id, enabled.target_id, enabled.mfa) == (str(the_owner.id), str(pat.id), True)
    assert enabled.change == {"status": {"before": "disabled", "after": "active"}}
    async with other_client(api) as pat_client:
        await sign_in(pat_client, clock, pat_secret, email=PERSON)
        assert (await pat_client.get("/api/auth/me")).status_code == 200


async def test_reset_forces_enrolment_at_the_next_sign_in(api, clock):
    the_owner = await owner(api, clock)
    pat, pat_secret = await make_user(
        email=PERSON, name="Pat Person", platform_role=None, recovery_codes=["aaaa-bbbb-cccc"]
    )
    async with other_client(api) as pat_client:
        await sign_in(pat_client, clock, pat_secret, email=PERSON)
        (pat_session,) = await sessions_of(pat.id)

        response = await api.post(f"/api/users/{pat.id}/mfa-reset")

        assert response.status_code == 204, response.text
        assert (await pat_client.get("/api/auth/me")).status_code == 401
        again = await login(pat_client)
        assert (again.status_code, again.json()) == (200, {"status": "enrolment_required"})

    stored = await load_user(PERSON)
    assert (stored.totp_secret, stored.totp_confirmed_at) == (None, None)
    async with SessionLocal() as session:
        assert (await session.scalars(select(RecoveryCode).where(RecoveryCode.user_id == pat.id))).all() == []
    (reset,) = await events("auth.mfa_reset")
    assert (reset.actor_id, reset.target_type, reset.target_id, reset.mfa) == (
        str(the_owner.id),
        "user",
        str(pat.id),
        True,
    )
    assert reset.result_detail == {"sessions_ended": 1}
    (revoked,) = await events("auth.session_revoked")
    assert (revoked.actor_id, revoked.target_id) == (str(the_owner.id), str(pat_session.id))


async def test_the_owner_cannot_disable_enable_or_reset_their_own_account(api, clock):
    the_owner = await owner(api, clock)

    for route in ("disable", "enable", "mfa-reset"):
        response = await api.post(f"/api/users/{the_owner.id}/{route}")
        assert (response.status_code, response.json()) == (409, {"detail": "own_account"}), route

    stored = await load_user()
    assert (stored.disabled_at, stored.totp_secret is not None) == (None, True)
    assert not {"user.disabled", "user.enabled", "auth.mfa_reset"} & set(await actions())


async def test_disabling_another_owner_leaves_at_least_one(api, clock):
    a, a_secret = await make_user(email="a@example.com", name="Ann Owner")
    b, b_secret = await make_user(email="b@example.com", name="Ben Owner")
    await sign_in(api, clock, a_secret, email="a@example.com")
    async with other_client(api) as b_client:
        await sign_in(b_client, clock, b_secret, email="b@example.com")

        response = await api.post(f"/api/users/{b.id}/disable")

        assert response.status_code == 204, response.text
        assert (await b_client.post(f"/api/users/{a.id}/disable")).status_code == 401

    async with SessionLocal() as session:
        owners = (
            await session.scalars(select(User).where(User.platform_role == "owner", User.disabled_at.is_(None)))
        ).all()
    assert [o.id for o in owners] == [a.id]

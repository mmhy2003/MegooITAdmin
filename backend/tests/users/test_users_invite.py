import hashlib
import uuid
from datetime import datetime, timedelta

from auth_helpers import add_grant, events, load_user, make_group, make_user, sign_in
from sqlalchemy import select

from app.access.permissions import Permission
from app.core.db import SessionLocal
from app.users.models import UserInvite

INVITEE = "ada@example.com"


def grant(group_id, role="admin", **switches) -> dict:
    """A grant as the request names it: every switch off unless given."""
    return {"group_id": str(group_id), "role": role, **{p.value: False for p in Permission}, **switches}


def invite_body(email=INVITEE, name="Ada Lovelace", platform_role=None, grants=()) -> dict:
    return {"name": name, "email": email, "platform_role": platform_role, "grants": list(grants)}


async def owner(api, clock):
    """The Owner, signed in on `api`."""
    user, secret = await make_user()
    await sign_in(api, clock, secret)
    return user


async def invites() -> list[UserInvite]:
    async with SessionLocal() as session:
        return list((await session.scalars(select(UserInvite))).all())


async def test_only_an_owner_may_list_or_invite(api, clock):
    staging = await make_group("staging")
    admin, secret = await make_user(email="admin@example.com", name="Al Admin", platform_role=None)
    await add_grant(admin.id, staging.id, "admin")
    await sign_in(api, clock, secret, email="admin@example.com")

    listed = await api.get("/api/users")
    invited = await api.post("/api/users", json=invite_body())

    assert (listed.status_code, listed.json()) == (403, {"detail": "forbidden"})
    assert (invited.status_code, invited.json()) == (403, {"detail": "forbidden"})
    denied = await events("access.denied")
    assert [(e.actor_id, e.result, e.result_detail) for e in denied] == [
        (str(admin.id), "failure", {"required": "owner", "route": "GET /api/users"}),
        (str(admin.id), "failure", {"required": "owner", "route": "POST /api/users"}),
    ]
    assert await events("user.invited") == []


async def test_an_invite_creates_an_account_without_a_password_and_returns_the_token_once(api, clock):
    await owner(api, clock)

    response = await api.post("/api/users", json=invite_body())

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"user_id", "token", "expires_at"}
    assert datetime.fromisoformat(body["expires_at"]) == clock.now + timedelta(days=7)
    user = await load_user(INVITEE)
    assert str(user.id) == body["user_id"]
    assert (user.name, user.password_hash, user.platform_role, user.disabled_at) == ("Ada Lovelace", None, None, None)
    (invite,) = await invites()
    assert invite.user_id == user.id
    assert invite.token_hash == hashlib.sha256(body["token"].encode()).digest()
    assert body["token"].encode() not in invite.token_hash
    assert invite.expires_at == clock.now + timedelta(days=7)
    # The list never shows the token again.
    assert body["token"] not in (await api.get("/api/users")).text


async def test_the_list_shows_the_status_the_grants_and_when_the_invite_expires(api, clock):
    the_owner = await owner(api, clock)
    staging = await make_group("staging")
    production = await make_group("Production")
    gone, _ = await make_user(email="gone@example.com", name="Gil Gone", platform_role=None, disabled=True)
    response = await api.post(
        "/api/users",
        json=invite_body(
            grants=[grant(staging.id, "admin", connect_ssh=True), grant(production.id, "operator", view_logs=True)]
        ),
    )
    invitee_id = response.json()["user_id"]

    response = await api.get("/api/users")

    assert response.status_code == 200, response.text
    rows = response.json()
    assert [row["name"] for row in rows] == ["Ada Lovelace", "Gil Gone", "Olive Owner"]
    ada, gil, olive = rows
    assert ada == {
        "id": invitee_id,
        "name": "Ada Lovelace",
        "email": INVITEE,
        "platform_role": None,
        "status": "invited",
        "mfa_enrolled": False,
        "invite_expires_at": ada["invite_expires_at"],
        "grants": [
            grant(production.id, "operator", view_logs=True) | {"group_name": "Production"},
            grant(staging.id, "admin", connect_ssh=True) | {"group_name": "staging"},
        ],
    }
    assert datetime.fromisoformat(ada["invite_expires_at"]) == clock.now + timedelta(days=7)
    assert (gil["id"], gil["status"], gil["invite_expires_at"], gil["grants"]) == (str(gone.id), "disabled", None, [])
    assert (olive["id"], olive["status"], olive["mfa_enrolled"], olive["platform_role"]) == (
        str(the_owner.id),
        "active",
        True,
        "owner",
    )


async def test_an_invite_records_the_account_and_each_grant(api, clock):
    the_owner = await owner(api, clock)
    staging = await make_group("staging")
    production = await make_group("production")

    response = await api.post(
        "/api/users",
        json=invite_body(grants=[grant(staging.id, "admin", connect_ssh=True), grant(production.id, "operator")]),
    )
    auditor = await api.post(
        "/api/users", json=invite_body(email="aud@example.com", name="Aud Itor", platform_role="auditor")
    )

    assert response.status_code == auditor.status_code == 200
    invitee_id = response.json()["user_id"]
    first, second = await events("user.invited")
    assert (first.actor_id, first.target_type, first.target_id, first.target_name) == (
        str(the_owner.id),
        "user",
        invitee_id,
        INVITEE,
    )
    assert (first.result, first.mfa) == ("success", True)
    assert first.change == {
        "name": {"before": None, "after": "Ada Lovelace"},
        "email": {"before": None, "after": INVITEE},
    }
    assert second.change == {
        "name": {"before": None, "after": "Aud Itor"},
        "email": {"before": None, "after": "aud@example.com"},
        "platform_role": {"before": None, "after": "auditor"},
    }
    added = await events("user.grant_added")
    assert sorted((e.context["server_group_id"], e.result_detail["server_group"]) for e in added) == sorted(
        [(str(staging.id), "staging"), (str(production.id), "production")]
    )
    for event in added:
        assert (event.actor_id, event.target_id) == (str(the_owner.id), invitee_id)
        assert all(field["before"] is None for field in event.change.values())
    by_group = {e.result_detail["server_group"]: e.change for e in added}
    assert by_group["staging"]["role"] == {"before": None, "after": "admin"}
    assert by_group["staging"]["connect_ssh"] == {"before": None, "after": True}
    assert by_group["production"]["manage_playbooks"] == {"before": None, "after": False}
    assert len(by_group["production"]) == 1 + len(Permission)
    # No event holds the token.
    token = response.json()["token"]
    for action in ("user.invited", "user.grant_added"):
        for event in await events(action):
            assert token not in repr(event.change) + repr(event.result_detail) + repr(event.context)


async def test_a_second_invite_for_the_same_email_gets_409(api, clock):
    await owner(api, clock)
    assert (await api.post("/api/users", json=invite_body())).status_code == 200

    for email in (INVITEE, "  ADA@Example.COM "):
        response = await api.post("/api/users", json=invite_body(email=email))
        assert (response.status_code, response.json()) == (409, {"detail": "email_taken"})
    assert len(await invites()) == 1
    assert len(await events("user.invited")) == 1


async def test_an_unknown_group_a_duplicate_group_or_an_operator_with_manage_playbooks_gets_422(api, clock):
    await owner(api, clock)
    staging = await make_group("staging")

    unknown = await api.post("/api/users", json=invite_body(grants=[grant(uuid.uuid4())]))
    twice = await api.post("/api/users", json=invite_body(grants=[grant(staging.id), grant(staging.id, "operator")]))
    operator = await api.post(
        "/api/users", json=invite_body(grants=[grant(staging.id, "operator", manage_playbooks=True)])
    )

    assert (unknown.status_code, unknown.json()) == (422, {"detail": "unknown_group"})
    assert twice.status_code == 422
    assert operator.status_code == 422
    assert len(await invites()) == 0
    assert await events("user.invited") == []


async def test_a_platform_role_with_group_roles_gets_422(api, clock):
    await owner(api, clock)
    staging = await make_group("staging")

    response = await api.post("/api/users", json=invite_body(platform_role="auditor", grants=[grant(staging.id)]))

    assert response.status_code == 422
    assert len(await invites()) == 0
    assert await events("user.invited") == []

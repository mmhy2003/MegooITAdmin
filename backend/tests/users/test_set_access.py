import asyncio
import uuid

from auth_helpers import actions, add_grant, events, make_group, make_user, other_client, sign_in
from sqlalchemy import select

from app.access.models import RoleGrant
from app.access.permissions import Permission
from app.auth.models import User
from app.core.db import SessionLocal

PERSON = "pat@example.com"
USER_EVENTS = ("user.role_changed", "user.grant_added", "user.grant_changed", "user.grant_removed")


def grant(group_id, role="admin", **switches) -> dict:
    """A grant as the request names it: every switch off unless given."""
    return {"group_id": str(group_id), "role": role, **{p.value: False for p in Permission}, **switches}


def fields_of(request_grant: dict) -> dict:
    """A request's grant as RoleGrant.fields() gives it: the role and the seven switches."""
    return {k: v for k, v in request_grant.items() if k != "group_id"}


def access(platform_role=None, grants=()) -> dict:
    return {"platform_role": platform_role, "grants": list(grants)}


async def owner(api, clock) -> User:
    """The Owner, signed in on `api`."""
    user, secret = await make_user()
    await sign_in(api, clock, secret)
    return user


async def person(**kwargs) -> User:
    user, _ = await make_user(email=PERSON, name="Pat Person", platform_role=None, **kwargs)
    return user


async def stored_grants(user_id) -> dict[uuid.UUID, dict]:
    async with SessionLocal() as session:
        grants = await session.scalars(select(RoleGrant).where(RoleGrant.user_id == user_id))
        return {g.server_group_id: g.fields() for g in grants}


async def user_events() -> list[str]:
    return [a for a in await actions() if a in USER_EVENTS]


async def test_adding_a_group_role_records_grant_added(api, clock):
    the_owner = await owner(api, clock)
    pat = await person()
    staging = await make_group("staging")

    response = await api.put(f"/api/users/{pat.id}/access", json=access(grants=[grant(staging.id, connect_ssh=True)]))

    assert response.status_code == 204, response.text
    assert await stored_grants(pat.id) == {staging.id: fields_of(grant(staging.id, connect_ssh=True))}
    (added,) = await events("user.grant_added")
    assert (added.actor_id, added.target_type, added.target_id, added.target_name) == (
        str(the_owner.id),
        "user",
        str(pat.id),
        PERSON,
    )
    assert (added.result, added.mfa) == ("success", True)
    assert added.context == {"server_group_id": str(staging.id)}
    assert added.result_detail == {"server_group": "staging"}
    assert added.change["role"] == {"before": None, "after": "admin"}
    assert added.change["connect_ssh"] == {"before": None, "after": True}
    assert all(field["before"] is None for field in added.change.values())
    assert len(added.change) == 1 + len(Permission)
    assert await user_events() == ["user.grant_added"]


async def test_changing_a_switch_records_grant_changed_with_before_and_after(api, clock):
    await owner(api, clock)
    pat = await person()
    staging = await make_group("staging")
    await add_grant(pat.id, staging.id, "admin", **{p.value: False for p in Permission})

    response = await api.put(f"/api/users/{pat.id}/access", json=access(grants=[grant(staging.id, view_logs=True)]))

    assert response.status_code == 204, response.text
    assert (await stored_grants(pat.id))[staging.id]["view_logs"] is True
    (changed,) = await events("user.grant_changed")
    assert changed.change == {"view_logs": {"before": False, "after": True}}
    assert changed.context == {"server_group_id": str(staging.id)}
    assert changed.result_detail == {"server_group": "staging"}
    assert await user_events() == ["user.grant_changed"]


async def test_changing_the_role_in_a_group_records_grant_changed(api, clock):
    await owner(api, clock)
    pat = await person()
    staging = await make_group("staging")
    await add_grant(pat.id, staging.id, "admin", **{p.value: False for p in Permission})

    response = await api.put(f"/api/users/{pat.id}/access", json=access(grants=[grant(staging.id, "operator")]))

    assert response.status_code == 204, response.text
    assert (await stored_grants(pat.id))[staging.id]["role"] == "operator"
    (changed,) = await events("user.grant_changed")
    assert changed.change == {"role": {"before": "admin", "after": "operator"}}


async def test_removing_a_group_records_grant_removed_with_after_none(api, clock):
    await owner(api, clock)
    pat = await person()
    staging = await make_group("staging")
    production = await make_group("production")
    await add_grant(pat.id, staging.id, "admin")
    await add_grant(pat.id, production.id, "operator")
    kept = await stored_grants(pat.id)

    response = await api.put(
        f"/api/users/{pat.id}/access",
        json=access(grants=[{"group_id": str(staging.id), **kept[staging.id]}]),
    )

    assert response.status_code == 204, response.text
    assert list(await stored_grants(pat.id)) == [staging.id]
    (removed,) = await events("user.grant_removed")
    assert removed.context == {"server_group_id": str(production.id)}
    assert removed.result_detail == {"server_group": "production"}
    assert removed.change["role"] == {"before": "operator", "after": None}
    assert all(field["after"] is None for field in removed.change.values())
    assert len(removed.change) == 1 + len(Permission)
    assert await user_events() == ["user.grant_removed"]


async def test_choosing_auditor_removes_the_group_roles_and_records_role_changed(api, clock):
    the_owner = await owner(api, clock)
    pat = await person()
    staging = await make_group("staging")
    production = await make_group("Production")
    await add_grant(pat.id, staging.id, "admin")
    await add_grant(pat.id, production.id, "operator")

    response = await api.put(f"/api/users/{pat.id}/access", json=access("auditor"))

    assert response.status_code == 204, response.text
    assert await stored_grants(pat.id) == {}
    async with SessionLocal() as session:
        assert (await session.get(User, pat.id)).platform_role == "auditor"
    assert await user_events() == ["user.role_changed", "user.grant_removed", "user.grant_removed"]
    (role,) = await events("user.role_changed")
    assert role.change == {"platform_role": {"before": None, "after": "auditor"}}
    assert (role.actor_id, role.target_id, role.mfa) == (str(the_owner.id), str(pat.id), True)
    removed = await events("user.grant_removed")
    assert [e.result_detail["server_group"] for e in removed] == ["Production", "staging"]


async def test_a_save_that_changes_nothing_gets_409_no_change(api, clock):
    await owner(api, clock)
    pat = await person()
    staging = await make_group("staging")
    await add_grant(pat.id, staging.id, "admin", **{p.value: False for p in Permission})
    nobody, _ = await make_user(email="nobody@example.com", name="No Body", platform_role=None)

    same = await api.put(f"/api/users/{pat.id}/access", json=access(grants=[grant(staging.id)]))
    still_nothing = await api.put(f"/api/users/{nobody.id}/access", json=access())

    assert (same.status_code, same.json()) == (409, {"detail": "no_change"})
    assert (still_nothing.status_code, still_nothing.json()) == (409, {"detail": "no_change"})
    assert await user_events() == []


async def test_an_unknown_group_a_duplicate_group_or_an_operator_with_manage_playbooks_gets_422(api, clock):
    await owner(api, clock)
    pat = await person()
    staging = await make_group("staging")

    unknown = await api.put(f"/api/users/{pat.id}/access", json=access(grants=[grant(uuid.uuid4())]))
    twice = await api.put(
        f"/api/users/{pat.id}/access", json=access(grants=[grant(staging.id), grant(staging.id, "operator")])
    )
    operator = await api.put(
        f"/api/users/{pat.id}/access", json=access(grants=[grant(staging.id, "operator", manage_playbooks=True)])
    )

    assert (unknown.status_code, unknown.json()) == (422, {"detail": "unknown_group"})
    assert twice.status_code == 422
    assert operator.status_code == 422
    assert await stored_grants(pat.id) == {}
    assert await user_events() == []


async def test_the_owner_cannot_change_their_own_access(api, clock):
    the_owner = await owner(api, clock)

    response = await api.put(f"/api/users/{the_owner.id}/access", json=access("auditor"))

    assert (response.status_code, response.json()) == (409, {"detail": "own_account"})
    async with SessionLocal() as session:
        assert (await session.get(User, the_owner.id)).platform_role == "owner"
    assert await user_events() == []


async def test_an_unknown_account_gets_404(api, clock):
    await owner(api, clock)

    response = await api.put(f"/api/users/{uuid.uuid4()}/access", json=access("auditor"))

    assert (response.status_code, response.json()) == (404, {"detail": "not_found"})


async def test_two_owners_demoting_each_other_at_once_leave_one_owner(api, clock):
    a, a_secret = await make_user(email="a@example.com", name="Ann Owner")
    b, b_secret = await make_user(email="b@example.com", name="Bob Owner")
    await sign_in(api, clock, a_secret, email="a@example.com")
    async with other_client(api) as b_client:
        await sign_in(b_client, clock, b_secret, email="b@example.com")

        responses = await asyncio.gather(
            api.put(f"/api/users/{b.id}/access", json=access()),
            b_client.put(f"/api/users/{a.id}/access", json=access()),
        )

    assert sorted(r.status_code for r in responses) == [204, 403]
    async with SessionLocal() as session:
        owners = (
            await session.scalars(select(User).where(User.platform_role == "owner", User.disabled_at.is_(None)))
        ).all()
    assert len(owners) == 1
    assert len(await events("access.denied")) == 1
    assert len(await events("user.role_changed")) == 1


async def test_the_new_access_applies_to_the_persons_next_request(api, clock):
    await owner(api, clock)
    pat, pat_secret = await make_user(email=PERSON, name="Pat Person", platform_role=None)
    async with other_client(api) as pat_client:
        await sign_in(pat_client, clock, pat_secret, email=PERSON)
        assert (await pat_client.get("/api/users")).status_code == 403

        response = await api.put(f"/api/users/{pat.id}/access", json=access("owner"))

        assert response.status_code == 204, response.text
        assert (await pat_client.get("/api/users")).status_code == 200

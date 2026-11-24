from uuid import uuid4

from auth_helpers import actions, add_grant, events, make_group, make_server, make_user, sign_in
from sqlalchemy import func, select

from app.access.models import RoleGrant
from app.access.permissions import GRANT_FIELDS, Permission
from app.auth.models import User
from app.core.db import SessionLocal
from app.inventory.models import Server, ServerGroup

GROUP_EVENTS = ("user.grant_removed", "server_group.deleted")


async def owner(api, clock) -> User:
    """The Owner, signed in on `api`."""
    user, secret = await make_user()
    await sign_in(api, clock, secret)
    return user


async def role_grant_count() -> int:
    async with SessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(RoleGrant))


async def group_exists(group_id) -> bool:
    async with SessionLocal() as session:
        return await session.get(ServerGroup, group_id) is not None


async def group_events() -> list[str]:
    return [a for a in await actions() if a in GROUP_EVENTS]


async def test_deleting_a_group_removes_its_roles_and_records_each(api, clock):
    the_owner = await owner(api, clock)
    staging = await make_group("staging", "The staging servers")
    production = await make_group("production")
    pat, _ = await make_user(email="pat@example.com", name="Pat Person", platform_role=None)
    sam, _ = await make_user(email="sam@example.com", name="Sam Second", platform_role=None)
    pat_grant = await add_grant(pat.id, staging.id, "admin")
    sam_grant = await add_grant(sam.id, staging.id, "operator")
    await add_grant(pat.id, production.id, "operator")

    response = await api.delete(f"/api/server-groups/{staging.id}")

    assert response.status_code == 204, response.text
    assert not await group_exists(staging.id)
    assert await role_grant_count() == 1
    assert await group_events() == ["user.grant_removed", "user.grant_removed", "server_group.deleted"]
    removed = await events("user.grant_removed")
    assert {e.target_id: e.target_name for e in removed} == {str(pat.id): pat.email, str(sam.id): sam.email}
    for event in removed:
        assert (event.actor_id, event.target_type, event.mfa) == (str(the_owner.id), "user", True)
        assert event.context["server_group_id"] == str(staging.id)
        assert event.result_detail == {"server_group": "staging"}
    by_user = {e.target_id: e.change for e in removed}
    assert by_user[str(pat.id)] == {f: {"before": v, "after": None} for f, v in pat_grant.fields().items()}
    assert by_user[str(sam.id)] == {f: {"before": v, "after": None} for f, v in sam_grant.fields().items()}
    assert set(by_user[str(pat.id)]) == set(GRANT_FIELDS)
    (deleted,) = await events("server_group.deleted")
    assert (deleted.actor_id, deleted.result, deleted.mfa) == (str(the_owner.id), "success", True)
    assert (deleted.target_type, deleted.target_id, deleted.target_name) == ("server_group", str(staging.id), "staging")
    assert deleted.change == {
        "name": {"before": "staging", "after": None},
        "description": {"before": "The staging servers", "after": None},
    }


async def test_deleting_an_empty_group_records_only_the_deletion(api, clock):
    await owner(api, clock)
    staging = await make_group("staging")

    response = await api.delete(f"/api/server-groups/{staging.id}")

    assert response.status_code == 204, response.text
    assert not await group_exists(staging.id)
    assert await group_events() == ["server_group.deleted"]


async def test_a_group_that_holds_a_server_cannot_be_deleted(api, clock):
    await owner(api, clock)
    staging = await make_group("staging")
    pat, _ = await make_user(email="pat@example.com", name="Pat Person", platform_role=None)
    await add_grant(pat.id, staging.id, "admin")
    server = await make_server(staging.id, "web-01")

    response = await api.delete(f"/api/server-groups/{staging.id}")

    assert (response.status_code, response.json()) == (409, {"detail": "group_has_servers"})
    assert await group_exists(staging.id)
    assert await role_grant_count() == 1
    async with SessionLocal() as session:
        assert await session.get(Server, server.id) is not None
    assert await group_events() == []


async def test_only_an_owner_deletes(api, clock):
    staging = await make_group("staging")
    admin, secret = await make_user(email="pat@example.com", name="Pat Person", platform_role=None)
    await add_grant(admin.id, staging.id, "admin")
    await sign_in(api, clock, secret, email="pat@example.com")

    response = await api.delete(f"/api/server-groups/{staging.id}")

    assert (response.status_code, response.json()) == (403, {"detail": "forbidden"})
    assert await group_exists(staging.id)
    assert await role_grant_count() == 1
    denied = await events("access.denied")
    assert [(e.actor_id, e.result_detail) for e in denied] == [
        (str(admin.id), {"required": "owner", "route": "DELETE /api/server-groups/{group_id}"})
    ]
    assert await group_events() == []


async def test_deleting_an_unknown_group_gets_404(api, clock):
    await owner(api, clock)

    response = await api.delete(f"/api/server-groups/{uuid4()}")

    assert (response.status_code, response.json()) == (404, {"detail": "not_found"})
    assert await group_events() == []


async def test_saving_access_for_a_deleted_group_gets_422(api, clock):
    await owner(api, clock)
    staging = await make_group("staging")
    pat, _ = await make_user(email="pat@example.com", name="Pat Person", platform_role=None)
    assert (await api.delete(f"/api/server-groups/{staging.id}")).status_code == 204

    grant = {"group_id": str(staging.id), "role": "admin", **{p.value: False for p in Permission}}
    response = await api.put(f"/api/users/{pat.id}/access", json={"platform_role": None, "grants": [grant]})

    assert (response.status_code, response.json()) == (422, {"detail": "unknown_group"})
    assert await role_grant_count() == 0

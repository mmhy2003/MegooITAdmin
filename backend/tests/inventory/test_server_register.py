from uuid import uuid4

import pytest
from auth_helpers import add_grant, events, make_group, make_server, signed_in
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.inventory import servers
from app.inventory.models import Server

OWNER = "owner@example.com"
ADMIN = "ada@example.com"
AUDITOR = "aud@example.com"

SERVER_KEYS = {
    "id",
    "name",
    "address",
    "port",
    "os",
    "role",
    "tags",
    "group_id",
    "group_name",
    "connection_settings",
    "host_key",
    "host_key_state",
    "host_key_fingerprint",
    "host_key_type",
    "host_key_pinned_at",
    "host_key_changed_at",
    "host_key_offered",
    "created_at",
    "updated_at",
    "can_manage",
    "can_connect",
    "metrics_interval_seconds",
    "monitoring",
}


def body(group_id, name="db-01", **fields) -> dict:
    """A valid registration into the group, each field overridable."""
    return {"name": name, "address": "10.0.0.1", "group_id": str(group_id), "os": "linux", "port": 22} | fields


async def server_count() -> int:
    async with SessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(Server))


async def test_an_admin_registers_a_server_into_their_group(api, clock):
    staging = await make_group("staging")
    async with signed_in(api, clock, ADMIN) as (ada, client):
        await add_grant(ada.id, staging.id, "admin")

        # The body is the server itself, not wrapped in {"body": ...}.
        response = await client.post("/api/servers", json=body(staging.id, tags=["Web", " eu-west", "web"]))

    assert response.status_code == 200, response.text
    server = response.json()
    assert server.keys() == SERVER_KEYS
    assert (server["name"], server["address"], server["port"], server["os"], server["role"]) == (
        "db-01",
        "10.0.0.1",
        22,
        "linux",
        None,
    )
    assert (server["group_id"], server["group_name"]) == (str(staging.id), "staging")
    assert server["tags"] == ["eu-west", "web"]
    assert server["connection_settings"] == {"username": "megoo"}
    assert server["host_key"] is None
    assert server["host_key_state"] == "not_pinned"
    for field in ("fingerprint", "type", "pinned_at", "changed_at", "offered"):
        assert server[f"host_key_{field}"] is None
    assert server["can_manage"] is True
    assert server["can_connect"] is True
    assert server["created_at"] and server["updated_at"]
    assert server["metrics_interval_seconds"] == 5
    assert server["monitoring"] is None

    (created,) = await events("server.created")
    assert (created.actor_id, created.result, created.mfa) == (str(ada.id), "success", True)
    assert (created.target_type, created.target_id, created.target_name) == ("server", server["id"], "db-01")
    assert created.context == {"server_group_id": str(staging.id)}
    assert created.change == {
        "address": {"before": None, "after": "10.0.0.1"},
        "connection_settings": {"before": None, "after": {"username": "megoo"}},
        "group": {"before": None, "after": "staging"},
        "metrics_interval_seconds": {"before": None, "after": 5},
        "name": {"before": None, "after": "db-01"},
        "os": {"before": None, "after": "linux"},
        "port": {"before": None, "after": 22},
        "tags": {"before": None, "after": ["eu-west", "web"]},
    }


async def test_the_role_and_login_account_are_kept_and_recorded(api, clock):
    staging = await make_group("staging")
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.post(
            "/api/servers",
            json=body(staging.id, os="windows", port=3389, role="db", connection_settings={"username": "admin"}),
        )

    assert response.status_code == 200, response.text
    assert (response.json()["role"], response.json()["connection_settings"]) == ("db", {"username": "admin"})
    (created,) = await events("server.created")
    assert created.change["role"] == {"before": None, "after": "db"}
    assert created.change["connection_settings"] == {"before": None, "after": {"username": "admin"}}


async def refused(client, group_id, status, user_id):
    response = await client.post("/api/servers", json=body(group_id))
    detail = "forbidden" if status == 403 else "not_found"
    assert (response.status_code, response.json()) == (status, {"detail": detail})
    (denied,) = await events("access.denied")
    assert denied.actor_id == str(user_id)
    assert denied.result_detail == {"required": "admin", "route": "POST /api/servers"}
    assert (denied.target_type, denied.target_id) == ("server_group", str(group_id))
    assert await server_count() == 0
    assert await events("server.created") == []


async def test_registering_is_refused_403_in_a_group_where_the_person_is_operator(api, clock):
    staging = await make_group("staging")
    async with signed_in(api, clock, ADMIN) as (ada, client):
        await add_grant(ada.id, staging.id, "operator")
        await refused(client, staging.id, 403, ada.id)


async def test_registering_is_refused_404_in_a_group_they_do_not_see(api, clock):
    staging = await make_group("staging")
    production = await make_group("production")
    async with signed_in(api, clock, ADMIN) as (ada, client):
        await add_grant(ada.id, staging.id, "admin")
        await refused(client, production.id, 404, ada.id)


async def test_an_auditor_cannot_register(api, clock):
    staging = await make_group("staging")
    async with signed_in(api, clock, AUDITOR, "auditor") as (auditor, client):
        await refused(client, staging.id, 403, auditor.id)


async def test_names_clash_without_regard_to_case_and_across_groups(api, clock):
    staging = await make_group("staging")
    production = await make_group("production")
    await make_server(staging.id, "db-01")
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.post("/api/servers", json=body(production.id, name="DB-01"))

    assert (response.status_code, response.json()) == (409, {"detail": "server_name_taken"})
    assert await server_count() == 1
    assert await events("server.created") == []


async def test_a_name_that_loses_the_race_gets_409(api, clock, monkeypatch):
    staging = await make_group("staging")
    await make_server(staging.id, "db-01")

    # The other request inserts between the check and the write: only the unique index sees it.
    async def nothing_taken(db, name, server_id=None):
        return None

    monkeypatch.setattr(servers, "_check_name", nothing_taken)
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.post("/api/servers", json=body(staging.id, name="DB-01"))

    assert (response.status_code, response.json()) == (409, {"detail": "server_name_taken"})
    assert await server_count() == 1
    assert await events("server.created") == []


@pytest.mark.parametrize(
    "field",
    [
        {"name": "db 01"},
        {"name": "-db"},
        {"address": "bad host"},
        {"port": 0},
        {"port": 65536},
        {"os": "bsd"},
        {"tags": ["a b"]},
    ],
)
async def test_a_bad_field_answers_422(api, clock, field):
    staging = await make_group("staging")
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.post("/api/servers", json=body(staging.id, **field))

    assert response.status_code == 422, response.text
    assert await server_count() == 0


async def test_root_as_the_login_account_answers_422(api, clock):
    staging = await make_group("staging")
    server = await make_server(staging.id, "db-02")
    root = {"connection_settings": {"username": "root"}}
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        registered = await owner.post("/api/servers", json=body(staging.id, **root))
        edited = await owner.patch(f"/api/servers/{server.id}", json=root)

    assert registered.status_code == 422, registered.text
    assert edited.status_code == 422, edited.text
    assert await server_count() == 1
    assert await events("server.created") == []
    assert await events("server.changed") == []


async def test_a_windows_server_has_no_host_key_state(api, clock):
    staging = await make_group("staging")
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.post("/api/servers", json=body(staging.id, os="windows", port=3389))

    assert response.status_code == 200, response.text
    assert (response.json()["host_key_state"], response.json()["can_connect"]) == ("none", False)


async def test_can_connect_follows_connect_ssh(api, clock):
    staging = await make_group("staging")
    server = await make_server(staging.id, "db-01")
    async with (
        signed_in(api, clock, OWNER, "owner") as (_, owner),
        signed_in(api, clock, ADMIN) as (ada, operator),
        signed_in(api, clock, AUDITOR, "auditor") as (_, auditor),
    ):
        await add_grant(ada.id, staging.id, "operator", connect_ssh=False)
        seen = {}
        for name, client in (("owner", owner), ("operator", operator), ("auditor", auditor)):
            response = await client.get(f"/api/servers/{server.id}")
            assert response.status_code == 200, response.text
            seen[name] = response.json()["can_connect"]

    assert seen == {"owner": True, "operator": False, "auditor": False}


async def test_the_owner_registering_into_a_group_that_does_not_exist_gets_422_unknown_group(api, clock):
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.post("/api/servers", json=body(uuid4()))

    assert (response.status_code, response.json()) == (422, {"detail": "unknown_group"})
    assert await events("server.created") == []


async def test_the_tasks_sentence(api, clock):
    """An admin registers a server into a group, and it appears only to people with a grant on that group."""
    staging = await make_group("staging")
    production = await make_group("production")
    async with (
        signed_in(api, clock, OWNER, "owner") as (_, owner),
        signed_in(api, clock, ADMIN) as (ada, admin),
        signed_in(api, clock, AUDITOR, "auditor") as (_, auditor),
    ):
        await add_grant(ada.id, staging.id, "admin")
        on_staging = (await owner.post("/api/servers", json=body(staging.id, name="web-01"))).json()
        on_production = (await owner.post("/api/servers", json=body(production.id, name="db-01"))).json()

        hidden = await admin.get(f"/api/servers/{on_production['id']}")
        assert (hidden.status_code, hidden.json()) == (404, {"detail": "not_found"})
        seen = await admin.get(f"/api/servers/{on_staging['id']}")
        assert seen.status_code == 200, seen.text
        assert seen.json() == on_staging

        for client, can_manage in ((owner, True), (auditor, False)):
            for server in (on_staging, on_production):
                response = await client.get(f"/api/servers/{server['id']}")
                assert response.status_code == 200, response.text
                assert response.json() == server | {"can_manage": can_manage, "can_connect": can_manage}

        missing = await owner.get(f"/api/servers/{uuid4()}")
        assert (missing.status_code, missing.json()) == (404, {"detail": "not_found"})

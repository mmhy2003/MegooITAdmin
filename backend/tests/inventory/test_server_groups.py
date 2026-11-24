from uuid import uuid4

from auth_helpers import add_grant, events, make_group, make_server, make_user, other_client, sign_in, signed_in

from app.auth.models import User
from app.inventory import service as inventory_service

PERSON = "pat@example.com"


async def owner(api, clock) -> User:
    """The Owner, signed in on `api`."""
    user, secret = await make_user()
    await sign_in(api, clock, secret)
    return user


async def person(client, clock, platform_role: str | None = None) -> User:
    """Pat, with no group roles yet, signed in on `client`."""
    user, secret = await make_user(email=PERSON, name="Pat Person", platform_role=platform_role)
    await sign_in(client, clock, secret, email=PERSON)
    return user


def names(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [group["name"] for group in response.json()]


async def test_a_staging_only_admin_sees_staging_and_not_production(api, clock):
    staging = await make_group("staging")
    await make_group("production")
    admin = await person(api, clock)
    await add_grant(admin.id, staging.id, "admin")

    assert names(await api.get("/api/server-groups")) == ["staging"]


async def test_an_owner_and_an_auditor_see_every_group(api, clock):
    for name in ("staging", "Production", "dev"):
        await make_group(name)
    await owner(api, clock)
    async with other_client(api) as auditor_client:
        await person(auditor_client, clock, platform_role="auditor")

        assert names(await api.get("/api/server-groups")) == ["dev", "Production", "staging"]
        assert names(await auditor_client.get("/api/server-groups")) == ["dev", "Production", "staging"]


async def test_a_person_without_roles_sees_none(api, clock):
    await make_group("staging")
    await person(api, clock)

    assert names(await api.get("/api/server-groups")) == []


async def test_the_owner_sees_how_many_people_hold_a_role_and_others_do_not(api, clock):
    staging = await make_group("staging", "The staging servers")
    await owner(api, clock)
    async with other_client(api) as pat_client:
        pat = await person(pat_client, clock)
        await add_grant(pat.id, staging.id, "operator")

        as_owner = (await api.get("/api/server-groups")).json()
        as_pat = (await pat_client.get("/api/server-groups")).json()

    (group,) = as_owner
    assert group["id"] == str(staging.id)
    assert (group["name"], group["description"], group["member_count"]) == ("staging", "The staging servers", 1)
    assert group["created_at"]
    assert [g["member_count"] for g in as_pat] == [None]


async def test_each_group_says_how_many_servers_it_holds(api, clock):
    staging = await make_group("staging")
    production = await make_group("production")
    await make_group("dev")
    await make_server(staging.id, "web-01")
    await make_server(staging.id, "db-02")
    await make_server(production.id, "app-03")
    async with (
        signed_in(api, clock, "owner@example.com", "owner") as (_, owner_client),
        signed_in(api, clock, "ada@example.com") as (ada, admin_client),
    ):
        await add_grant(ada.id, staging.id, "admin")
        as_owner = (await owner_client.get("/api/server-groups")).json()
        as_admin = (await admin_client.get("/api/server-groups")).json()

    assert {g["name"]: g["server_count"] for g in as_owner} == {"dev": 0, "production": 1, "staging": 2}
    assert {g["name"]: g["server_count"] for g in as_admin} == {"staging": 2}


async def test_can_manage_is_true_for_the_owner_and_a_groups_admin_only(api, clock):
    staging = await make_group("staging")
    production = await make_group("production")
    async with (
        signed_in(api, clock, "owner@example.com", "owner") as (_, owner_client),
        signed_in(api, clock, "ada@example.com") as (ada, admin_client),
        signed_in(api, clock, "aud@example.com", "auditor") as (_, auditor_client),
    ):
        await add_grant(ada.id, staging.id, "admin")
        await add_grant(ada.id, production.id, "operator")
        as_owner = (await owner_client.get("/api/server-groups")).json()
        as_admin = (await admin_client.get("/api/server-groups")).json()
        as_auditor = (await auditor_client.get("/api/server-groups")).json()

    assert {g["name"]: g["can_manage"] for g in as_owner} == {"production": True, "staging": True}
    assert {g["name"]: g["can_manage"] for g in as_admin} == {"production": False, "staging": True}
    assert {g["name"]: g["can_manage"] for g in as_auditor} == {"production": False, "staging": False}


async def test_the_owner_creates_a_group_and_it_is_recorded(api, clock):
    the_owner = await owner(api, clock)

    response = await api.post("/api/server-groups", json={"name": "  staging ", "description": ""})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["name"], body["description"], body["member_count"]) == ("staging", None, 0)
    assert (body["server_count"], body["can_manage"]) == (0, True)
    assert names(await api.get("/api/server-groups")) == ["staging"]
    (created,) = await events("server_group.created")
    assert (created.actor_id, created.result, created.mfa) == (str(the_owner.id), "success", True)
    assert (created.target_type, created.target_id, created.target_name) == ("server_group", body["id"], "staging")
    assert created.change == {"name": {"before": None, "after": "staging"}}


async def test_names_clash_without_regard_to_case(api, clock):
    await owner(api, clock)
    await make_group("Staging")
    production = await make_group("production")

    created = await api.post("/api/server-groups", json={"name": "staging"})
    renamed = await api.patch(f"/api/server-groups/{production.id}", json={"name": "STAGING"})

    assert (created.status_code, created.json()) == (409, {"detail": "name_taken"})
    assert (renamed.status_code, renamed.json()) == (409, {"detail": "name_taken"})
    assert await events("server_group.created") == []
    assert await events("server_group.changed") == []


async def test_a_name_that_loses_the_race_gets_409(api, clock, monkeypatch):
    await owner(api, clock)
    await make_group("Staging")
    production = await make_group("production")

    # The other request inserts between the check and the write: only the unique index sees it.
    async def nothing_taken(db, name, group_id=None):
        return None

    monkeypatch.setattr(inventory_service, "_check_name", nothing_taken)
    created = await api.post("/api/server-groups", json={"name": "staging"})
    renamed = await api.patch(f"/api/server-groups/{production.id}", json={"name": "STAGING"})

    assert (created.status_code, created.json()) == (409, {"detail": "name_taken"})
    assert (renamed.status_code, renamed.json()) == (409, {"detail": "name_taken"})
    assert await events("server_group.created") == []
    assert await events("server_group.changed") == []


async def test_a_name_must_have_1_to_64_characters(api, clock):
    await owner(api, clock)
    group = await make_group("staging")

    for name in ("", "   ", "x" * 65):
        assert (await api.post("/api/server-groups", json={"name": name})).status_code == 422
        assert (await api.patch(f"/api/server-groups/{group.id}", json={"name": name})).status_code == 422
    assert (await api.post("/api/server-groups", json={"name": "x" * 64})).status_code == 200


async def test_the_owner_edits_a_group(api, clock):
    the_owner = await owner(api, clock)
    group = await make_group("staging", "Old words")

    described = await api.patch(f"/api/server-groups/{group.id}", json={"description": "New words"})
    renamed = await api.patch(f"/api/server-groups/{group.id}", json={"name": "Staging"})

    assert described.status_code == 200, described.text
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["name"], renamed.json()["description"]) == ("Staging", "New words")
    assert (renamed.json()["server_count"], renamed.json()["can_manage"]) == (0, True)
    first, second = await events("server_group.changed")
    assert (first.actor_id, first.target_type, first.target_id, first.target_name) == (
        str(the_owner.id),
        "server_group",
        str(group.id),
        "staging",
    )
    assert first.change == {"description": {"before": "Old words", "after": "New words"}}
    assert second.target_name == "Staging"
    assert second.change == {"name": {"before": "staging", "after": "Staging"}}


async def test_an_edit_that_changes_nothing_gets_409_no_change(api, clock):
    await owner(api, clock)
    group = await make_group("staging", "Words")

    for body in ({}, {"name": "staging"}, {"name": " staging ", "description": "Words"}):
        response = await api.patch(f"/api/server-groups/{group.id}", json=body)
        assert (response.status_code, response.json()) == (409, {"detail": "no_change"})
    assert await events("server_group.changed") == []


async def test_only_an_owner_creates_or_edits(api, clock):
    staging = await make_group("staging")
    admin = await person(api, clock)
    await add_grant(admin.id, staging.id, "admin")

    created = await api.post("/api/server-groups", json={"name": "production"})
    edited = await api.patch(f"/api/server-groups/{staging.id}", json={"name": "prod"})

    assert (created.status_code, created.json()) == (403, {"detail": "forbidden"})
    assert (edited.status_code, edited.json()) == (403, {"detail": "forbidden"})
    denied = await events("access.denied")
    assert [(e.actor_id, e.result, e.result_detail) for e in denied] == [
        (str(admin.id), "failure", {"required": "owner", "route": "POST /api/server-groups"}),
        (str(admin.id), "failure", {"required": "owner", "route": "PATCH /api/server-groups/{group_id}"}),
    ]
    assert await events("server_group.created") == []
    assert await events("server_group.changed") == []


async def test_an_unknown_group_gets_404(api, clock):
    await owner(api, clock)

    response = await api.patch(f"/api/server-groups/{uuid4()}", json={"name": "staging"})

    assert (response.status_code, response.json()) == (404, {"detail": "not_found"})

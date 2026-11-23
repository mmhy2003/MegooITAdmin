from uuid import uuid4

import pytest
from auth_helpers import add_grant, events, make_group, make_server, signed_in
from sqlalchemy import select

from app.core.db import SessionLocal
from app.inventory.models import Server

OWNER = "owner@example.com"
ADMIN = "ada@example.com"
OPERATOR = "otto@example.com"
EDIT_ACTIONS = ("server.changed", "server.moved", "server.tags_changed")


async def edit_events() -> list:
    """The edit events, in the order they were recorded."""
    found = [event for action in EDIT_ACTIONS for event in await events(action)]
    return sorted(found, key=lambda event: event.seq)


async def stored(server_id) -> Server:
    async with SessionLocal() as session:
        return await session.scalar(select(Server).where(Server.id == server_id))


async def test_changing_fields_records_server_changed(api, clock):
    staging = await make_group("staging")
    server = await make_server(staging.id, "db-01", tags=("web",))
    before = await stored(server.id)
    async with signed_in(api, clock, ADMIN) as (ada, client):
        await add_grant(ada.id, staging.id, "admin")
        response = await client.patch(f"/api/servers/{server.id}", json={"address": "10.0.0.2", "port": 2222})

    assert response.status_code == 200, response.text
    assert (response.json()["address"], response.json()["port"]) == ("10.0.0.2", 2222)
    assert response.json()["tags"] == ["web"]
    assert response.json()["updated_at"] > response.json()["created_at"]
    assert (await stored(server.id)).updated_at > before.updated_at

    (changed,) = await edit_events()
    assert (changed.action, changed.actor_id, changed.result, changed.mfa) == (
        "server.changed",
        str(ada.id),
        "success",
        True,
    )
    assert (changed.target_type, changed.target_id, changed.target_name) == ("server", str(server.id), "db-01")
    assert changed.context == {"server_group_id": str(staging.id)}
    assert changed.change == {
        "address": {"before": "10.0.0.1", "after": "10.0.0.2"},
        "port": {"before": 22, "after": 2222},
    }


async def test_changing_tags_records_server_tags_changed(api, clock):
    staging = await make_group("staging")
    server = await make_server(staging.id, "db-01", tags=("web", "eu-west"))
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.patch(f"/api/servers/{server.id}", json={"tags": ["Web", "db", "app"]})

    assert response.status_code == 200, response.text
    assert response.json()["tags"] == ["app", "db", "web"]
    (tags_changed,) = await edit_events()
    assert tags_changed.action == "server.tags_changed"
    assert tags_changed.change == {"tags": {"before": ["eu-west", "web"], "after": ["app", "db", "web"]}}
    assert tags_changed.result_detail is None


async def test_one_save_with_fields_group_and_tags_records_three_events_in_order(api, clock):
    staging = await make_group("staging")
    production = await make_group("production")
    server = await make_server(staging.id, "db-01", tags=("web",))
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.patch(
            f"/api/servers/{server.id}",
            json={"name": "db-02", "role": "db", "group_id": str(production.id), "tags": ["db"]},
        )

    assert response.status_code == 200, response.text
    assert (response.json()["name"], response.json()["group_name"], response.json()["tags"]) == (
        "db-02",
        "production",
        ["db"],
    )
    changed, moved, tags_changed = await edit_events()
    assert [changed.action, moved.action, tags_changed.action] == list(EDIT_ACTIONS)
    assert changed.change == {"name": {"before": "db-01", "after": "db-02"}, "role": {"before": None, "after": "db"}}
    assert moved.change == {"group": {"before": "staging", "after": "production"}}
    assert tags_changed.change == {"tags": {"before": ["web"], "after": ["db"]}}
    for event in (changed, moved, tags_changed):
        assert event.target_name == "db-02"
        assert event.context == {"server_group_id": str(production.id)}


@pytest.mark.parametrize(
    "patch",
    [
        {},
        {"name": "db-01", "port": 22, "os": "linux"},
        {"tags": ["Web", "eu-west"]},
        {"address": "DB-01.EXAMPLE.COM"},
        {"role": ""},
        {"connection_settings": {"username": "megoo"}},
    ],
)
async def test_a_save_that_changes_nothing_answers_409_no_change(api, clock, patch):
    staging = await make_group("staging")
    server = await make_server(staging.id, "db-01", address="db-01.example.com", tags=("eu-west", "web"))
    before = await stored(server.id)
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.patch(
            f"/api/servers/{server.id}", json=patch | ({"group_id": str(staging.id)} if patch else {})
        )

    assert (response.status_code, response.json()) == (409, {"detail": "no_change"})
    assert (await stored(server.id)).updated_at == before.updated_at
    assert await edit_events() == []


async def test_renaming_onto_a_taken_name_answers_409(api, clock):
    staging = await make_group("staging")
    production = await make_group("production")
    server = await make_server(staging.id, "db-01")
    await make_server(production.id, "db-02")
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        taken = await owner.patch(f"/api/servers/{server.id}", json={"name": "DB-02"})
        assert (taken.status_code, taken.json()) == (409, {"detail": "server_name_taken"})
        assert await edit_events() == []

        # Its own name in another case is a rename.
        recased = await owner.patch(f"/api/servers/{server.id}", json={"name": "DB-01"})

    assert recased.status_code == 200, recased.text
    (changed,) = await edit_events()
    assert changed.change == {"name": {"before": "db-01", "after": "DB-01"}}


async def move(client, server_id, group_id):
    return await client.patch(f"/api/servers/{server_id}", json={"group_id": str(group_id)})


async def test_a_move_needs_admin_on_both_groups(api, clock):
    staging = await make_group("staging")
    production = await make_group("production")
    server = await make_server(staging.id, "db-01")
    async with (
        signed_in(api, clock, ADMIN) as (ada, both),
        signed_in(api, clock, "half@example.com") as (half, operator_there),
        signed_in(api, clock, "sam@example.com") as (sam, staging_only),
        signed_in(api, clock, OPERATOR) as (otto, production_operator),
    ):
        await add_grant(ada.id, staging.id, "admin")
        await add_grant(ada.id, production.id, "admin")
        await add_grant(half.id, staging.id, "admin")
        await add_grant(half.id, production.id, "operator")
        await add_grant(sam.id, staging.id, "admin")
        await add_grant(otto.id, production.id, "operator")

        refused = await move(operator_there, server.id, production.id)
        assert (refused.status_code, refused.json()) == (403, {"detail": "forbidden"})
        hidden = await move(staging_only, server.id, production.id)
        assert (hidden.status_code, hidden.json()) == (404, {"detail": "not_found"})
        assert (await stored(server.id)).server_group_id == staging.id
        denied = await events("access.denied")
        assert [(event.actor_id, event.target_id) for event in denied] == [
            (str(half.id), str(production.id)),
            (str(sam.id), str(production.id)),
        ]

        response = await move(both, server.id, production.id)
        assert response.status_code == 200, response.text
        assert (response.json()["group_id"], response.json()["group_name"]) == (str(production.id), "production")

        gone = await staging_only.get(f"/api/servers/{server.id}")
        assert (gone.status_code, gone.json()) == (404, {"detail": "not_found"})
        seen = await production_operator.get(f"/api/servers/{server.id}")
        assert seen.status_code == 200, seen.text

    (moved,) = await edit_events()
    assert (moved.action, moved.actor_id) == ("server.moved", str(ada.id))
    assert moved.change == {"group": {"before": "staging", "after": "production"}}
    assert moved.result_detail == {"from_group_id": str(staging.id), "to_group_id": str(production.id)}
    assert moved.context == {"server_group_id": str(production.id)}


async def test_an_operator_cannot_edit(api, clock):
    staging = await make_group("staging")
    server = await make_server(staging.id, "db-01")
    async with signed_in(api, clock, OPERATOR) as (otto, client):
        await add_grant(otto.id, staging.id, "operator")
        response = await client.patch(f"/api/servers/{server.id}", json={"port": 2222})

    assert (response.status_code, response.json()) == (403, {"detail": "forbidden"})
    assert (await stored(server.id)).port == 22
    assert await edit_events() == []


async def test_editing_a_server_that_does_not_exist_answers_404(api, clock):
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.patch(f"/api/servers/{uuid4()}", json={"port": 2222})

    assert (response.status_code, response.json()) == (404, {"detail": "not_found"})


async def test_the_owner_moving_into_a_missing_group_gets_422_unknown_group(api, clock):
    staging = await make_group("staging")
    server = await make_server(staging.id, "db-01")
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await move(owner, server.id, uuid4())

    assert (response.status_code, response.json()) == (422, {"detail": "unknown_group"})
    assert (await stored(server.id)).server_group_id == staging.id
    assert await edit_events() == []

from uuid import uuid4

from auth_helpers import add_grant, events, make_group, make_server, signed_in
from conftest import owner_session
from sqlalchemy import delete

from app.inventory.models import Server

OWNER = "owner@example.com"
ADA = "ada@example.com"
BEN = "ben@example.com"
ROUTE = "/api/log-views"


def view(server_id, **kw) -> dict:
    """A body with one journal source of the server."""
    return {"name": "Web errors", "sources": [{"server_id": str(server_id), "kind": "journal"}]} | kw


def names(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [v["name"] for v in response.json()]


async def saved(client, body: dict) -> dict:
    response = await client.post(ROUTE, json=body)
    assert response.status_code == 200, response.text
    return response.json()


async def test_the_owner_of_a_view_replaces_it(api, clock):
    staging = await make_group("staging")
    web, db = await make_server(staging.id, "web-01"), await make_server(staging.id, "db-02")
    async with signed_in(api, clock, ADA) as (ada, client):
        await add_grant(ada.id, staging.id, "operator")
        first = await saved(client, view(web.id))
        body = view(
            db.id,
            name="DB errors",
            shared=True,
            settings={"q": "timeout", "regex": True, "levels": ["error"], "layout": "merged", "wrap": True,
                      "utc": True},
        )
        replaced = await client.put(f"{ROUTE}/{first['id']}", json=body)
        listed = await client.get(ROUTE)

    assert replaced.status_code == 200, replaced.text
    after = replaced.json()
    assert (after["id"], after["name"], after["shared"]) == (first["id"], "DB errors", True)
    assert after["sources"] == [
        {"server_id": str(db.id), "kind": "journal", "unit": None, "priority": None, "this_boot": False}
    ]
    assert after["settings"] == body["settings"]
    assert after["updated_at"] > first["updated_at"]
    assert listed.json() == [after]
    (event,) = await events("log_view.updated")
    assert (event.actor_id, event.result, event.mfa) == (str(ada.id), "success", True)
    assert (event.target_type, event.target_id, event.target_name) == ("log_view", first["id"], "DB errors")
    assert event.change == {
        "name": {"before": "Web errors", "after": "DB errors"},
        "shared": {"before": False, "after": True},
        "sources": {"before": first["sources"], "after": after["sources"]},
        "settings": {"before": first["settings"], "after": body["settings"]},
    }


async def test_the_event_holds_only_the_changed_fields(api, clock):
    staging = await make_group("staging")
    web = await make_server(staging.id, "web-01")
    async with signed_in(api, clock, ADA) as (ada, client):
        await add_grant(ada.id, staging.id, "operator")
        first = await saved(client, view(web.id))
        replaced = await client.put(f"{ROUTE}/{first['id']}", json=view(web.id, name="Renamed"))

    assert replaced.status_code == 200, replaced.text
    (event,) = await events("log_view.updated")
    assert event.change == {"name": {"before": "Web errors", "after": "Renamed"}}


async def test_the_platform_owner_replaces_and_deletes_a_shared_view(api, clock):
    staging = await make_group("staging")
    web = await make_server(staging.id, "web-01")
    async with (
        signed_in(api, clock, OWNER, "owner") as (owner, owner_client),
        signed_in(api, clock, ADA) as (ada, ada_client),
    ):
        await add_grant(ada.id, staging.id, "operator")
        shared = await saved(ada_client, view(web.id, shared=True))
        replaced = await owner_client.put(f"{ROUTE}/{shared['id']}", json=view(web.id, name="Kept", shared=True))
        deleted = await owner_client.delete(f"{ROUTE}/{shared['id']}")
        left = await ada_client.get(ROUTE)

    assert replaced.status_code == 200, replaced.text
    assert (replaced.json()["owner_name"], replaced.json()["is_mine"], replaced.json()["can_edit"]) == (
        "ada", False, True
    )
    assert (deleted.status_code, deleted.content) == (204, b"")
    assert names(left) == []
    (updated,) = await events("log_view.updated")
    (removed,) = await events("log_view.deleted")
    assert updated.actor_id == removed.actor_id == str(owner.id)


async def test_another_reader_of_a_shared_view_gets_403(api, clock):
    staging = await make_group("staging")
    web = await make_server(staging.id, "web-01")
    async with (
        signed_in(api, clock, ADA) as (ada, ada_client),
        signed_in(api, clock, BEN) as (ben, ben_client),
    ):
        await add_grant(ada.id, staging.id, "operator")
        await add_grant(ben.id, staging.id, "admin")
        shared = await saved(ada_client, view(web.id, shared=True))
        put = await ben_client.put(f"{ROUTE}/{shared['id']}", json=view(web.id, name="Mine now", shared=True))
        deleted = await ben_client.delete(f"{ROUTE}/{shared['id']}")
        listed = await ada_client.get(ROUTE)

    assert (put.status_code, put.json()) == (403, {"detail": "forbidden"})
    assert (deleted.status_code, deleted.json()) == (403, {"detail": "forbidden"})
    assert listed.json() == [shared]


async def test_a_private_view_of_another_and_a_shared_one_out_of_reach_answer_404(api, clock):
    staging, production = await make_group("staging"), await make_group("production")
    web, app = await make_server(staging.id, "web-01"), await make_server(production.id, "app-02")
    async with (
        signed_in(api, clock, OWNER, "owner") as (_, owner_client),
        signed_in(api, clock, ADA) as (ada, ada_client),
        signed_in(api, clock, BEN) as (ben, ben_client),
    ):
        await add_grant(ada.id, staging.id, "operator")
        await add_grant(ada.id, production.id, "operator")
        await add_grant(ben.id, staging.id, "admin")
        private = await saved(ada_client, view(web.id, name="Private"))
        sources = [{"server_id": str(web.id), "kind": "journal"}, {"server_id": str(app.id), "kind": "journal"}]
        out_of_reach = await saved(ada_client, view(web.id, name="Both", shared=True, sources=sources))
        answers = []
        for client, target in (
            (ben_client, private), (owner_client, private), (ben_client, out_of_reach), (ben_client, {"id": uuid4()})
        ):
            answers.append(await client.put(f"{ROUTE}/{target['id']}", json=view(web.id, name="Taken")))
            answers.append(await client.delete(f"{ROUTE}/{target['id']}"))
        listed = await ada_client.get(ROUTE)

    assert [(a.status_code, a.json()) for a in answers] == [(404, {"detail": "not_found"})] * 8
    assert names(listed) == ["Both", "Private"]
    assert await events("log_view.updated") == [] and await events("log_view.deleted") == []


async def test_a_put_that_changes_nothing_answers_409_no_change(api, clock):
    staging = await make_group("staging")
    web = await make_server(staging.id, "web-01")
    async with signed_in(api, clock, ADA) as (ada, client):
        await add_grant(ada.id, staging.id, "operator")
        first = await saved(client, view(web.id))
        same = await client.put(f"{ROUTE}/{first['id']}", json=view(web.id, name=" Web errors "))

    assert (same.status_code, same.json()) == (409, {"detail": "no_change"})
    assert await events("log_view.updated") == []


async def test_put_applies_the_save_checks(api, clock):
    staging, production = await make_group("staging"), await make_group("production")
    web = await make_server(staging.id, "web-01")
    app = await make_server(production.id, "app-02")
    hidden = await make_server((await make_group("hidden")).id, "x-03")
    async with signed_in(api, clock, ADA) as (ada, client):
        await add_grant(ada.id, staging.id, "operator")
        await add_grant(ada.id, production.id, "operator", view_logs=False)
        first = await saved(client, view(web.id))
        await saved(client, view(web.id, name="Other"))
        url = f"{ROUTE}/{first['id']}"
        unseen = await client.put(url, json=view(hidden.id))
        no_logs = await client.put(url, json=view(app.id))
        clash = await client.put(url, json=view(web.id, name="OTHER"))
        own_name = await client.put(url, json=view(web.id, name="WEB ERRORS"))

    assert (unseen.status_code, unseen.json()) == (404, {"detail": "not_found"})
    assert (no_logs.status_code, no_logs.json()) == (403, {"detail": "forbidden"})
    assert (clash.status_code, clash.json()) == (409, {"detail": "view_name_taken"})
    assert own_name.status_code == 200, own_name.text  # its own name in another case is no clash
    assert own_name.json()["name"] == "WEB ERRORS"


async def test_deleting_records_log_view_deleted(api, clock):
    staging = await make_group("staging")
    web = await make_server(staging.id, "web-01")
    async with signed_in(api, clock, ADA) as (ada, client):
        await add_grant(ada.id, staging.id, "operator")
        first = await saved(client, view(web.id, shared=True))
        deleted = await client.delete(f"{ROUTE}/{first['id']}")
        again = await client.delete(f"{ROUTE}/{first['id']}")
        listed = await client.get(ROUTE)

    assert (deleted.status_code, deleted.content) == (204, b"")
    assert (again.status_code, again.json()) == (404, {"detail": "not_found"})
    assert names(listed) == []
    (event,) = await events("log_view.deleted")
    assert (event.actor_id, event.result, event.mfa) == (str(ada.id), "success", True)
    assert (event.target_type, event.target_id, event.target_name) == ("log_view", first["id"], "Web errors")
    assert event.change == {
        "name": {"before": "Web errors", "after": None},
        "shared": {"before": True, "after": None},
        "sources": {"before": first["sources"], "after": None},
        "settings": {"before": first["settings"], "after": None},
    }


async def test_a_disabled_owners_shared_views_stay(api, clock):
    staging = await make_group("staging")
    web = await make_server(staging.id, "web-01")
    async with (
        signed_in(api, clock, OWNER, "owner") as (_, owner_client),
        signed_in(api, clock, ADA) as (ada, ada_client),
        signed_in(api, clock, BEN) as (ben, ben_client),
    ):
        await add_grant(ada.id, staging.id, "operator")
        await add_grant(ben.id, staging.id, "operator")
        await saved(ada_client, view(web.id, shared=True))
        disabled = await owner_client.post(f"/api/users/{ada.id}/disable")
        listed = await ben_client.get(ROUTE)

    assert disabled.status_code == 204, disabled.text
    assert names(listed) == ["Web errors"]
    assert listed.json()[0]["owner_name"] == "ada"


async def test_a_view_naming_a_lost_server_stays_in_its_owners_list(api, clock):
    staging = await make_group("staging")
    web, db = await make_server(staging.id, "web-01"), await make_server(staging.id, "db-02")
    sources = [{"server_id": str(web.id), "kind": "journal"}, {"server_id": str(db.id), "kind": "journal"}]
    async with signed_in(api, clock, ADA) as (ada, client):
        await add_grant(ada.id, staging.id, "operator")
        first = await saved(client, view(web.id, sources=sources))
        async with owner_session() as session:
            await session.execute(delete(Server).where(Server.id == db.id))
            await session.commit()
        listed = await client.get(ROUTE)
        deleted = await client.delete(f"{ROUTE}/{first['id']}")

    assert listed.json() == [first]
    assert deleted.status_code == 204, deleted.text  # the owner still removes it

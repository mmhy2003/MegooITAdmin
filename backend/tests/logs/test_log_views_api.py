from uuid import uuid4

import pytest
from auth_helpers import add_grant, events, make_group, make_server, signed_in
from sqlalchemy import update

from app.core.db import SessionLocal
from app.inventory.models import Server
from app.logs.models import LogView

OWNER = "owner@example.com"
ADA = "ada@example.com"
BEN = "ben@example.com"
ROUTE = "/api/log-views"
SETTINGS = {
    "q": "",
    "regex": False,
    "levels": ["error", "warning", "info", "debug", "none"],
    "layout": "side_by_side",
    "wrap": False,
    "utc": False,
}


def view(server_id, **kw) -> dict:
    """A POST body with one journal source of the server."""
    return {"name": "Web errors", "sources": [{"server_id": str(server_id), "kind": "journal"}]} | kw


def names(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [v["name"] for v in response.json()]


async def test_a_person_saves_a_view_and_lists_it(api, clock):
    staging = await make_group("staging")
    web = await make_server(staging.id, "web-01")
    async with signed_in(api, clock, ADA) as (ada, client):
        await add_grant(ada.id, staging.id, "operator")
        saved = await client.post(ROUTE, json=view(web.id))
        listed = await client.get(ROUTE)

    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert set(body) == {"id", "name", "shared", "owner_name", "is_mine", "can_edit", "sources", "settings",
                         "updated_at"}
    assert (body["name"], body["shared"], body["owner_name"]) == ("Web errors", False, "ada")
    assert (body["is_mine"], body["can_edit"]) == (True, True)
    assert body["sources"] == [
        {"server_id": str(web.id), "kind": "journal", "unit": None, "priority": None, "this_boot": False}
    ]
    assert body["settings"] == SETTINGS
    assert body["updated_at"]
    assert listed.json() == [body]


async def test_a_container_source_keeps_its_name(api, clock):
    staging = await make_group("staging")
    web = await make_server(staging.id, "web-01")
    source = {"server_id": str(web.id), "kind": "container", "container_id": "3f2a9c", "name": "nginx"}
    async with signed_in(api, clock, ADA) as (ada, client):
        await add_grant(ada.id, staging.id, "operator")
        saved = await client.post(ROUTE, json=view(web.id, sources=[source]))
        listed = await client.get(ROUTE)

    assert saved.status_code == 200, saved.text
    assert saved.json()["sources"] == [source]
    assert listed.json()[0]["sources"] == [source]


async def test_a_shared_view_is_listed_for_who_reads_every_server(api, clock):
    g1, g2 = await make_group("g1"), await make_group("g2")
    one, two = await make_server(g1.id, "one-01"), await make_server(g2.id, "two-01")
    turned = await make_server(g1.id, "three-01")
    sources = [{"server_id": str(one.id), "kind": "journal"}, {"server_id": str(two.id), "kind": "journal"}]
    async with (
        signed_in(api, clock, OWNER, "owner") as (_, owner_client),
        signed_in(api, clock, ADA) as (ada, ada_client),
        signed_in(api, clock, "admin@example.com") as (admin, admin_client),
        signed_in(api, clock, "solo@example.com") as (solo, solo_client),
        signed_in(api, clock, "blind@example.com") as (blind, blind_client),
        signed_in(api, clock, "auditor@example.com", "auditor") as (_, auditor_client),
    ):
        await add_grant(ada.id, g1.id, "operator")
        await add_grant(ada.id, g2.id, "operator")  # the Owner gives Ada g2 too
        await add_grant(admin.id, g1.id, "admin")
        await add_grant(admin.id, g2.id, "admin")
        await add_grant(solo.id, g1.id, "operator")
        await add_grant(blind.id, g1.id, "operator")
        await add_grant(blind.id, g2.id, "operator", view_logs=False)
        both = await ada_client.post(ROUTE, json=view(one.id, name="Both", shared=True, sources=sources))
        windows = await ada_client.post(ROUTE, json=view(turned.id, name="Windows", shared=True))
        async with SessionLocal() as session:  # a server that turned Windows after the save
            await session.execute(update(Server).where(Server.id == turned.id).values(os="windows"))
            await session.commit()
        lists = {
            name: await client.get(ROUTE)
            for name, client in (("owner", owner_client), ("admin", admin_client), ("solo", solo_client),
                                 ("blind", blind_client), ("auditor", auditor_client))
        }

    assert both.status_code == 200 and windows.status_code == 200, (both.text, windows.text)
    assert {name: names(response) for name, response in lists.items()} == {
        "owner": ["Both", "Windows"],  # the Owner sees every shared view
        "admin": ["Both"],
        "solo": [],
        "blind": [],
        "auditor": [],
    }
    shown = lists["admin"].json()[0]
    assert (shown["owner_name"], shown["is_mine"], shown["can_edit"]) == ("ada", False, False)
    assert [(v["is_mine"], v["can_edit"]) for v in lists["owner"].json()] == [(False, True), (False, True)]


async def test_a_private_view_is_nobody_elses(api, clock):
    staging = await make_group("staging")
    web = await make_server(staging.id, "web-01")
    async with (
        signed_in(api, clock, OWNER, "owner") as (_, owner_client),
        signed_in(api, clock, ADA) as (ada, ada_client),
        signed_in(api, clock, BEN) as (ben, ben_client),
    ):
        await add_grant(ada.id, staging.id, "admin")
        await add_grant(ben.id, staging.id, "admin")
        saved = await ada_client.post(ROUTE, json=view(web.id))
        as_owner, as_ben = await owner_client.get(ROUTE), await ben_client.get(ROUTE)

    assert saved.status_code == 200, saved.text
    assert names(as_owner) == [] and names(as_ben) == []


async def test_saving_refuses_a_server_out_of_sight_404_and_without_view_logs_403(api, clock):
    staging, production = await make_group("staging"), await make_group("production")
    web = await make_server(staging.id, "web-01")
    win = await make_server(staging.id, "win-02", os="windows", port=3389)
    app = await make_server(production.id, "app-03")
    hidden = await make_server((await make_group("hidden")).id, "x-01")
    async with signed_in(api, clock, ADA) as (ada, client):
        await add_grant(ada.id, staging.id, "operator")
        await add_grant(ada.id, production.id, "operator", view_logs=False)
        unseen = await client.post(ROUTE, json=view(uuid4()))
        mixed = [{"server_id": str(web.id), "kind": "journal"}, {"server_id": str(hidden.id), "kind": "journal"}]
        out_of_sight = await client.post(ROUTE, json=view(web.id, sources=mixed))
        no_logs = await client.post(ROUTE, json=view(app.id))
        windows = await client.post(ROUTE, json=view(win.id))
        listed = await client.get(ROUTE)

    assert (unseen.status_code, unseen.json()) == (404, {"detail": "not_found"})
    assert (out_of_sight.status_code, out_of_sight.json()) == (404, {"detail": "not_found"})
    assert (no_logs.status_code, no_logs.json()) == (403, {"detail": "forbidden"})
    assert (windows.status_code, windows.json()) == (403, {"detail": "forbidden"})
    assert names(listed) == []
    assert await events("log_view.created") == []


async def test_the_name_is_unique_per_owner_without_regard_to_case(api, clock):
    staging = await make_group("staging")
    web = await make_server(staging.id, "web-01")
    async with (
        signed_in(api, clock, ADA) as (ada, ada_client),
        signed_in(api, clock, BEN) as (ben, ben_client),
    ):
        await add_grant(ada.id, staging.id, "operator")
        await add_grant(ben.id, staging.id, "operator")
        first = await ada_client.post(ROUTE, json=view(web.id, name="Web errors"))
        clash = await ada_client.post(ROUTE, json=view(web.id, name="  WEB ERRORS "))
        other = await ben_client.post(ROUTE, json=view(web.id, name="Web errors"))

    assert first.status_code == 200, first.text
    assert (clash.status_code, clash.json()) == (409, {"detail": "view_name_taken"})
    assert other.status_code == 200, other.text


async def test_the_101st_view_is_refused(api, clock):
    staging = await make_group("staging")
    web = await make_server(staging.id, "web-01")
    async with signed_in(api, clock, ADA) as (ada, client):
        await add_grant(ada.id, staging.id, "operator")
        async with SessionLocal() as session:
            session.add_all(
                LogView(owner_id=ada.id, name=f"View {n}", sources=view(web.id)["sources"], settings=SETTINGS)
                for n in range(100)
            )
            await session.commit()
        refused = await client.post(ROUTE, json=view(web.id, name="One more"))

    assert (refused.status_code, refused.json()) == (409, {"detail": "too_many_views"})


SERVER = "00000000-0000-0000-0000-000000000001"
JOURNAL = {"server_id": SERVER, "kind": "journal"}


@pytest.mark.parametrize(
    "body",
    [
        {"name": "No source", "sources": []},
        {"name": "Too many", "sources": [JOURNAL] * 17},
        {"name": "Bad unit", "sources": [JOURNAL | {"unit": "-rf"}]},
        {"name": "Climbs", "sources": [{"server_id": SERVER, "kind": "file", "path": "/var/log/../shadow"}]},
        {"name": "Long filter", "sources": [JOURNAL], "settings": {"q": "x" * 201}},
        {"name": "Fatal", "sources": [JOURNAL], "settings": {"levels": ["fatal"]}},
        {"name": "Extra", "sources": [JOURNAL], "colour": "pink"},
        {"name": "x" * 81, "sources": [JOURNAL]},
        {"name": "   ", "sources": [JOURNAL]},
    ],
    ids=["no-source", "17-sources", "bad-unit", "dot-dot", "201-q", "fatal", "extra-field", "81-name", "blank-name"],
)
async def test_invalid_bodies_answer_422(api, clock, body):
    async with signed_in(api, clock, ADA) as (_, client):
        response = await client.post(ROUTE, json=body)

    assert response.status_code == 422, response.text


async def test_the_levels_are_deduplicated_in_their_order(api, clock):
    staging = await make_group("staging")
    web = await make_server(staging.id, "web-01")
    async with signed_in(api, clock, ADA) as (ada, client):
        await add_grant(ada.id, staging.id, "operator")
        saved = await client.post(ROUTE, json=view(web.id, settings={"levels": ["none", "error", "none"]}))

    assert saved.status_code == 200, saved.text
    assert saved.json()["settings"]["levels"] == ["error", "none"]


async def test_saving_records_log_view_created(api, clock):
    staging = await make_group("staging")
    web = await make_server(staging.id, "web-01")
    async with signed_in(api, clock, ADA) as (ada, client):
        await add_grant(ada.id, staging.id, "operator")
        saved = await client.post(ROUTE, json=view(web.id, name=" Web errors ", shared=True))

    body = saved.json()
    (event,) = await events("log_view.created")
    assert (event.actor_id, event.result, event.mfa) == (str(ada.id), "success", True)
    assert (event.target_type, event.target_id, event.target_name) == ("log_view", body["id"], "Web errors")
    assert event.change == {
        "name": {"before": None, "after": "Web errors"},
        "shared": {"before": None, "after": True},
        "sources": {"before": None, "after": body["sources"]},
        "settings": {"before": None, "after": SETTINGS},
    }

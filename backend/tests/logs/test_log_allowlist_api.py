from uuid import uuid4

from auth_helpers import add_grant, events, make_group, signed_in
from logs_helpers import add_pattern
from sqlalchemy import select

from app.core.db import SessionLocal
from app.logs.allowlist import STARTER_PATTERNS, patterns_of, starter_rows
from app.logs.models import LogFileAllowlist

OWNER = "owner@example.com"
ADA = "ada@example.com"


def route(group_id) -> str:
    return f"/api/server-groups/{group_id}/log-allowlist"


async def rows(group_id) -> list[str]:
    async with SessionLocal() as session:
        query = select(LogFileAllowlist.pattern).where(LogFileAllowlist.server_group_id == group_id)
        return sorted((await session.scalars(query)).all())


async def test_a_member_lists_the_patterns_and_learns_they_cannot_manage(api, clock):
    staging = await make_group("staging")
    await add_pattern(staging.id, "/var/log/syslog")
    await add_pattern(staging.id, "/var/log/nginx/*.log")
    async with (
        signed_in(api, clock, OWNER, "owner") as (_, owner_client),
        signed_in(api, clock, ADA) as (ada, operator_client),
    ):
        await add_grant(ada.id, staging.id, "operator")
        as_operator = await operator_client.get(route(staging.id))
        as_owner = await owner_client.get(route(staging.id))

    assert as_operator.status_code == 200, as_operator.text
    body = as_operator.json()
    assert body["can_manage"] is False
    assert [p["pattern"] for p in body["patterns"]] == ["/var/log/nginx/*.log", "/var/log/syslog"]
    assert all(p["id"] and p["created_at"] for p in body["patterns"])
    assert as_owner.json()["can_manage"] is True


async def test_an_admin_adds_a_pattern_and_it_is_recorded(api, clock):
    staging = await make_group("staging")
    async with signed_in(api, clock, ADA) as (ada, client):
        await add_grant(ada.id, staging.id, "admin")
        response = await client.post(route(staging.id), json={"pattern": "/srv/app/*.log"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pattern"] == "/srv/app/*.log"
    assert await rows(staging.id) == ["/srv/app/*.log"]
    (added,) = await events("log_allowlist.pattern_added")
    assert (added.actor_id, added.result, added.mfa) == (str(ada.id), "success", True)
    assert (added.target_type, added.target_id, added.target_name) == ("server_group", str(staging.id), "staging")
    assert added.change == {"pattern": {"before": None, "after": "/srv/app/*.log"}}
    assert added.result_detail == {"pattern_id": body["id"]}


async def test_an_admin_removes_a_pattern_and_it_is_recorded(api, clock):
    staging = await make_group("staging")
    await add_pattern(staging.id, "/var/log/syslog")
    async with signed_in(api, clock, ADA) as (ada, client):
        await add_grant(ada.id, staging.id, "admin")
        (pattern,) = (await client.get(route(staging.id))).json()["patterns"]
        removed = await client.delete(f"{route(staging.id)}/{pattern['id']}")
        again = await client.delete(f"{route(staging.id)}/{pattern['id']}")

    assert removed.status_code == 204, removed.text
    assert (again.status_code, again.json()) == (404, {"detail": "not_found"})
    assert await rows(staging.id) == []
    (event,) = await events("log_allowlist.pattern_removed")
    assert (event.actor_id, event.target_id, event.target_name) == (str(ada.id), str(staging.id), "staging")
    assert event.change == {"pattern": {"before": "/var/log/syslog", "after": None}}
    assert event.result_detail == {"pattern_id": pattern["id"]}


async def test_a_pattern_of_another_group_is_not_found(api, clock):
    staging = await make_group("staging")
    production = await make_group("production")
    await add_pattern(production.id, "/var/log/syslog")
    async with signed_in(api, clock, OWNER, "owner") as (_, client):
        (pattern,) = (await client.get(route(production.id))).json()["patterns"]
        response = await client.delete(f"{route(staging.id)}/{pattern['id']}")

    assert (response.status_code, response.json()) == (404, {"detail": "not_found"})
    assert await rows(production.id) == ["/var/log/syslog"]
    assert await events("log_allowlist.pattern_removed") == []


async def test_an_invalid_pattern_is_422(api, clock):
    staging = await make_group("staging")
    async with signed_in(api, clock, OWNER, "owner") as (_, client):
        responses = [await client.post(route(staging.id), json={"pattern": p}) for p in ("/*", "/var/log/../x")]
        extra = await client.post(route(staging.id), json={"pattern": "/var/log/syslog", "extra": 1})

    assert [r.status_code for r in responses] == [422, 422]
    assert extra.status_code == 422
    assert await rows(staging.id) == []
    assert await events("log_allowlist.pattern_added") == []


async def test_a_duplicate_is_409_pattern_exists(api, clock):
    staging = await make_group("staging")
    await add_pattern(staging.id, "/var/log/syslog")
    async with signed_in(api, clock, OWNER, "owner") as (_, client):
        response = await client.post(route(staging.id), json={"pattern": "/var/log/syslog"})

    assert (response.status_code, response.json()) == (409, {"detail": "pattern_exists"})
    assert await events("log_allowlist.pattern_added") == []


async def test_the_51st_pattern_is_409_too_many_patterns(api, clock):
    staging = await make_group("staging")
    for n in range(50):
        await add_pattern(staging.id, f"/var/log/app-{n}.log")
    async with signed_in(api, clock, OWNER, "owner") as (_, client):
        response = await client.post(route(staging.id), json={"pattern": "/var/log/one-more.log"})

    assert (response.status_code, response.json()) == (409, {"detail": "too_many_patterns"})
    assert len(await rows(staging.id)) == 50
    assert await events("log_allowlist.pattern_added") == []


async def test_an_unseen_group_is_404_and_a_non_admin_is_403(api, clock):
    staging = await make_group("staging")
    production = await make_group("production")
    await add_pattern(staging.id, "/var/log/syslog")
    nowhere = uuid4()
    async with signed_in(api, clock, ADA) as (ada, client):
        await add_grant(ada.id, staging.id, "operator")
        unseen = await client.get(route(production.id))
        missing = await client.post(route(nowhere), json={"pattern": "/var/log/x.log"})
        added = await client.post(route(staging.id), json={"pattern": "/var/log/x.log"})
        removed = await client.delete(f"{route(staging.id)}/{uuid4()}")

    assert (unseen.status_code, unseen.json()) == (404, {"detail": "not_found"})
    assert (missing.status_code, missing.json()) == (404, {"detail": "not_found"})
    assert (added.status_code, added.json()) == (403, {"detail": "forbidden"})
    assert (removed.status_code, removed.json()) == (403, {"detail": "forbidden"})
    assert await rows(staging.id) == ["/var/log/syslog"]
    denied = await events("access.denied")
    template = "/api/server-groups/{group_id}/log-allowlist"
    assert [(e.target_id, e.result_detail) for e in denied] == [
        (str(production.id), {"required": "group", "route": f"GET {template}"}),
        (str(nowhere), {"required": "admin", "route": f"POST {template}"}),
        (str(staging.id), {"required": "admin", "route": f"POST {template}"}),
        (str(staging.id), {"required": "admin", "route": f"DELETE {template}/{{pattern_id}}"}),
    ]
    assert all(e.actor_id == str(ada.id) for e in denied)


async def test_patterns_of_gives_each_asked_group_its_sorted_patterns(api):
    staging = await make_group("staging")
    production = await make_group("production")
    empty = await make_group("empty")
    async with SessionLocal() as session:
        session.add_all(starter_rows(staging.id))
        await session.commit()
    await add_pattern(production.id, "/srv/b.log")
    await add_pattern(production.id, "/srv/a.log")

    async with SessionLocal() as session:
        found = await patterns_of(session, [staging.id, production.id, empty.id])

    assert found == {staging.id: sorted(STARTER_PATTERNS), production.id: ["/srv/a.log", "/srv/b.log"]}

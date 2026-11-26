import uuid

from auth_helpers import add_grant, events, make_group, make_server, make_user
from starlette.requests import HTTPConnection

from app.access.deps import load_access
from app.access.servers import record_hidden, split_visible
from app.core.db import SessionLocal

SCOPE = {
    "type": "websocket",
    "headers": [(b"user-agent", b"pytest")],
    "client": ("127.0.0.1", 5000),
    "path": "/api/ws/metrics",
    "query_string": b"",
}


async def split(user, ids):
    async with SessionLocal() as db:
        return await split_visible(db, await load_access(db, user), ids)


async def test_an_owner_sees_every_existing_server(api, clock):
    owner, _ = await make_user(platform_role="owner")
    staging = await make_group("staging")
    a = await make_server(staging.id, "a")
    b = await make_server(staging.id, "b")

    assert await split(owner, [a.id, b.id, uuid.uuid4()]) == ({a.id, b.id}, {})


async def test_a_group_member_sees_only_their_groups(api, clock):
    member, _ = await make_user(email="member@example.com", platform_role=None)
    staging = await make_group("staging")
    production = await make_group("production")
    await add_grant(member.id, staging.id, "operator")
    s1 = await make_server(staging.id, "s1")
    p1 = await make_server(production.id, "p1")

    assert await split(member, [s1.id, p1.id, uuid.uuid4()]) == ({s1.id}, {p1.id: production.id})


async def test_an_auditor_sees_everything(api, clock):
    auditor, _ = await make_user(email="auditor@example.com", platform_role="auditor")
    staging = await make_group("staging")
    production = await make_group("production")
    s1 = await make_server(staging.id, "s1")
    p1 = await make_server(production.id, "p1")

    assert await split(auditor, [s1.id, p1.id]) == ({s1.id, p1.id}, {})


async def test_nothing_asked_is_nothing_seen(api, clock):
    owner, _ = await make_user(platform_role="owner")

    assert await split(owner, []) == (frozenset(), {})


async def test_record_hidden_writes_one_access_denied_event(api, clock):
    member, _ = await make_user(email="member@example.com", platform_role=None)
    p1, p2 = uuid.uuid4(), uuid.uuid4()

    await record_hidden(HTTPConnection(SCOPE), member, "WS /api/ws/metrics", [p1, p2])

    [event] = await events("access.denied")
    assert (event.result, event.target_type, event.target_id, event.actor_id) == (
        "failure",
        None,
        None,
        str(member.id),
    )
    assert event.result_detail == {
        "required": "group",
        "route": "WS /api/ws/metrics",
        "server_ids": sorted([str(p1), str(p2)]),
    }
    assert (str(event.source_ip), event.user_agent, event.auth_method, event.mfa) == (
        "127.0.0.1",
        "pytest",
        "password",
        True,
    )


async def test_record_hidden_of_nothing_writes_nothing(api, clock):
    member, _ = await make_user(email="member@example.com", platform_role=None)

    await record_hidden(HTTPConnection(SCOPE), member, "WS /api/ws/metrics", [])

    assert await events("access.denied") == []

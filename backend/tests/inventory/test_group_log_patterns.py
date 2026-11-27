from auth_helpers import events, make_group, make_user, sign_in
from logs_helpers import add_pattern
from sqlalchemy import select

from app.core.db import SessionLocal
from app.logs.allowlist import STARTER_PATTERNS
from app.logs.models import LogFileAllowlist


async def owner(api, clock) -> None:
    """The Owner, signed in on `api`."""
    _, secret = await make_user()
    await sign_in(api, clock, secret)


async def rows(group_id) -> list[str]:
    async with SessionLocal() as session:
        query = select(LogFileAllowlist.pattern).where(LogFileAllowlist.server_group_id == group_id)
        return sorted((await session.scalars(query)).all())


async def test_a_new_group_gets_the_four_starter_patterns(api, clock):
    await owner(api, clock)

    created = await api.post("/api/server-groups", json={"name": "staging"})
    listed = await api.get(f"/api/server-groups/{created.json()['id']}/log-allowlist")

    assert listed.status_code == 200, listed.text
    assert [p["pattern"] for p in listed.json()["patterns"]] == sorted(STARTER_PATTERNS)
    assert len(STARTER_PATTERNS) == 4


async def test_the_created_event_carries_the_starter_patterns(api, clock):
    await owner(api, clock)

    response = await api.post("/api/server-groups", json={"name": "staging"})

    assert response.status_code == 200, response.text
    (created,) = await events("server_group.created")
    assert created.change["log_file_allowlist"] == {"before": None, "after": list(STARTER_PATTERNS)}


async def test_the_deleted_event_carries_the_groups_patterns_and_the_rows_go(api, clock):
    await owner(api, clock)
    staging = await make_group("staging")
    await add_pattern(staging.id, "/var/log/syslog")
    await add_pattern(staging.id, "/srv/app/*.log")

    response = await api.delete(f"/api/server-groups/{staging.id}")

    assert response.status_code == 204, response.text
    (deleted,) = await events("server_group.deleted")
    assert deleted.change["log_file_allowlist"] == {"before": ["/srv/app/*.log", "/var/log/syslog"], "after": None}
    assert await rows(staging.id) == []

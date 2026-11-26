"""The last result of a check and the containers of a server, written through the collector's role."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from auth_helpers import make_group, make_server
from conftest import owner_session
from sqlalchemy import text

from app.checks.models import SeenContainer
from app.checks.store import read_checks, read_containers, replace_containers, write_check

pytestmark = pytest.mark.usefixtures("clean_auth")

T1 = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
T2 = T1 + timedelta(seconds=30)


def _container(container_id: str, name: str, project: str | None = None, state: str = "running") -> SeenContainer:
    return SeenContainer(
        container_id=container_id,
        name=name,
        image=f"{name}:latest",
        compose_project=project,
        compose_service=name if project else None,
        state=state,
        status="Up 3 hours" if state == "running" else "Exited (0) 1 minute ago",
    )


async def _server_id() -> uuid.UUID:
    group = await make_group("Production")
    return (await make_server(group.id, "web-1")).id


async def test_a_first_ok_run_stores_its_data(collector_sessions):
    server_id = await _server_id()
    async with collector_sessions() as session:
        await write_check(session, server_id, "services", "ok", checked_at=T1, data={"failed": 1})
        await session.commit()
    async with collector_sessions() as session:
        check = (await read_checks(session, server_id))["services"]
    assert (check.status, check.checked_at, check.data, check.data_at) == ("ok", T1, {"failed": 1}, T1)


async def test_a_failed_run_keeps_the_last_good_data(collector_sessions):
    server_id = await _server_id()
    async with collector_sessions() as session:
        await write_check(session, server_id, "updates", "ok", checked_at=T1, data={"pending": 4})
        await session.commit()
        await write_check(session, server_id, "updates", "timeout", checked_at=T2, data=None)
        await session.commit()
    async with collector_sessions() as session:
        checks = await read_checks(session, server_id)
    check = checks["updates"]
    assert list(checks) == ["updates"]
    assert (check.status, check.checked_at, check.data, check.data_at) == ("timeout", T2, {"pending": 4}, T1)


async def test_a_first_failed_run_has_no_data(collector_sessions):
    server_id = await _server_id()
    async with collector_sessions() as session:
        await write_check(session, server_id, "logins", "denied", checked_at=T1, data=None)
        await session.commit()
        check = (await read_checks(session, server_id))["logins"]
    assert (check.status, check.data, check.data_at) == ("denied", None, None)


async def test_a_listing_adds_updates_and_deletes_and_keeps_first_seen(collector_sessions):
    server_id = await _server_id()
    async with collector_sessions() as session:
        await replace_containers(session, server_id, [_container("a1", "a"), _container("b1", "b")], seen_at=T1)
        await session.commit()
        await replace_containers(
            session, server_id, [_container("a1", "a", state="exited"), _container("c1", "c")], seen_at=T2
        )
        await session.commit()
    async with collector_sessions() as session:
        containers = {c.container_id: c for c in await read_containers(session, server_id)}
    assert sorted(containers) == ["a1", "c1"]
    a = containers["a1"]
    assert (a.first_seen_at, a.last_seen_at, a.state, a.status) == (T1, T2, "exited", "Exited (0) 1 minute ago")
    assert (containers["c1"].first_seen_at, containers["c1"].runtime) == (T2, "docker")


async def test_an_empty_listing_removes_every_container(collector_sessions):
    server_id = await _server_id()
    async with collector_sessions() as session:
        await replace_containers(session, server_id, [_container("a1", "a"), _container("b1", "b")], seen_at=T1)
        await session.commit()
        await replace_containers(session, server_id, [], seen_at=T2)
        await session.commit()
        assert await read_containers(session, server_id) == []


async def test_a_listing_leaves_other_servers_alone(collector_sessions):
    group = await make_group("Production")
    first = (await make_server(group.id, "web-1")).id
    second = (await make_server(group.id, "web-2")).id
    async with collector_sessions() as session:
        await replace_containers(session, first, [_container("a1", "a")], seen_at=T1)
        await replace_containers(session, second, [_container("a1", "a")], seen_at=T1)
        await session.commit()
        await replace_containers(session, first, [], seen_at=T2)
        await session.commit()
        assert [c.name for c in await read_containers(session, second)] == ["a"]


async def test_read_containers_orders_by_project_then_name(collector_sessions):
    server_id = await _server_id()
    listing = [
        _container("1", "zeta"),
        _container("2", "worker", "shop"),
        _container("3", "api", "shop"),
        _container("4", "db", "billing"),
        _container("5", "alpha"),
    ]
    async with collector_sessions() as session:
        await replace_containers(session, server_id, listing, seen_at=T1)
        await session.commit()
        containers = await read_containers(session, server_id)
    assert [(c.compose_project, c.name) for c in containers] == [
        ("billing", "db"),
        ("shop", "api"),
        ("shop", "worker"),
        (None, "alpha"),
        (None, "zeta"),
    ]


async def test_rows_go_with_their_server(collector_sessions):
    server_id = await _server_id()
    async with collector_sessions() as session:
        await write_check(session, server_id, "services", "ok", checked_at=T1, data={"failed": 0})
        await replace_containers(session, server_id, [_container("a1", "a")], seen_at=T1)
        await session.commit()
    async with owner_session() as session:
        await session.execute(text("DELETE FROM servers WHERE id = :id"), {"id": server_id})
        await session.commit()
        checks = await session.scalar(text("SELECT count(*) FROM server_checks WHERE server_id = :id"), {"id": server_id})
        containers = await session.scalar(text("SELECT count(*) FROM containers WHERE server_id = :id"), {"id": server_id})
    assert (checks, containers) == (0, 0)

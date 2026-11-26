"""GET /api/servers/{id}/checks and /containers: everyone who sees the server reads them; the processes data needs
View processes."""

from datetime import UTC, datetime, timedelta

import pytest
from auth_helpers import add_grant, events, make_group, make_server, signed_in
from conftest import owner_session

from app.checks.models import KINDS, Container, ServerCheck

OWNER = "owner@example.com"
OPERATOR = "otto@example.com"
T1 = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
T2 = T1 + timedelta(hours=1)


async def _add(*rows) -> None:
    async with owner_session() as session:
        session.add_all(rows)
        await session.commit()


def _container(server_id, container_id: str, name: str, project: str | None) -> Container:
    return Container(
        server_id=server_id,
        runtime="docker",
        container_id=container_id,
        name=name,
        image=f"{name}:latest",
        compose_project=project,
        compose_service=name if project else None,
        state="running",
        status="Up 3 hours",
        first_seen_at=T1,
        last_seen_at=T2,
    )


async def test_a_server_without_results_has_six_not_checked_checks(api, clock):
    server = await make_server((await make_group("staging")).id, "web-1")
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.get(f"/api/servers/{server.id}/checks")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["can_view_processes"] is True
    assert [check["kind"] for check in body["checks"]] == list(KINDS)
    assert [check["every_seconds"] for check in body["checks"]] == [30, 30, 60, 300, 3600, 21600]
    assert {(c["status"], c["checked_at"], c["data"], c["data_at"]) for c in body["checks"]} == {
        ("not_checked", None, None, None)
    }


async def test_results_and_kept_data_are_returned(api, clock):
    server = await make_server((await make_group("staging")).id, "web-1")
    await _add(
        ServerCheck(server_id=server.id, kind="services", status="ok", checked_at=T2, data={"failed": []}, data_at=T2),
        ServerCheck(
            server_id=server.id, kind="updates", status="timeout", checked_at=T2, data={"pending": 4}, data_at=T1
        ),
    )
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.get(f"/api/servers/{server.id}/checks")

    checks = {check["kind"]: check for check in response.json()["checks"]}
    assert checks["services"]["status"] == "ok"
    assert checks["services"]["data"] == {"failed": []}
    assert datetime.fromisoformat(checks["services"]["data_at"]) == T2
    assert checks["updates"]["status"] == "timeout"
    assert datetime.fromisoformat(checks["updates"]["checked_at"]) == T2
    assert checks["updates"]["data"] == {"pending": 4}
    assert datetime.fromisoformat(checks["updates"]["data_at"]) == T1


async def _processes_as_operator(api, clock, **switches):
    staging = await make_group("staging")
    server = await make_server(staging.id, "web-1")
    data = {"cpu": [{"name": "postgres", "cpu": 12.5}], "memory": []}
    await _add(ServerCheck(server_id=server.id, kind="processes", status="ok", checked_at=T1, data=data, data_at=T1))
    async with signed_in(api, clock, OPERATOR) as (otto, client):
        await add_grant(otto.id, staging.id, "operator", **switches)
        response = await client.get(f"/api/servers/{server.id}/checks")
    assert response.status_code == 200, response.text
    body = response.json()
    return body, next(check for check in body["checks"] if check["kind"] == "processes"), data


async def test_an_operator_with_view_processes_sees_the_processes_data(api, clock):
    body, processes, data = await _processes_as_operator(api, clock, view_processes=True)

    assert body["can_view_processes"] is True
    assert processes["data"] == data
    assert datetime.fromisoformat(processes["data_at"]) == T1


async def test_without_view_processes_the_processes_data_is_hidden(api, clock):
    body, processes, _ = await _processes_as_operator(api, clock, view_processes=False)

    assert body["can_view_processes"] is False
    assert (processes["status"], processes["data"], processes["data_at"]) == ("ok", None, None)
    assert datetime.fromisoformat(processes["checked_at"]) == T1
    assert await events("access.denied") == []


async def test_containers_are_listed_by_project_then_name(api, clock):
    server = await make_server((await make_group("staging")).id, "web-1")
    await _add(
        _container(server.id, "c1", "zeta", None),
        _container(server.id, "c2", "web", "shop"),
        _container(server.id, "c3", "db", "shop"),
        _container(server.id, "c4", "proxy", "edge"),
    )
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.get(f"/api/servers/{server.id}/containers")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [(c["compose_project"], c["name"]) for c in body] == [
        ("edge", "proxy"),
        ("shop", "db"),
        ("shop", "web"),
        (None, "zeta"),
    ]
    first = body[0]
    assert (first["container_id"], first["runtime"], first["image"], first["compose_service"]) == (
        "c4",
        "docker",
        "proxy:latest",
        "proxy",
    )
    assert (first["state"], first["status"]) == ("running", "Up 3 hours")
    assert datetime.fromisoformat(first["first_seen_at"]) == T1
    assert datetime.fromisoformat(first["last_seen_at"]) == T2


@pytest.mark.parametrize("path", ["checks", "containers"])
async def test_a_server_the_person_does_not_see_answers_404(api, clock, path):
    server = await make_server((await make_group("staging")).id, "web-1")
    other = await make_group("production")
    async with signed_in(api, clock, OPERATOR) as (otto, client):
        await add_grant(otto.id, other.id, "operator")
        response = await client.get(f"/api/servers/{server.id}/{path}")

    assert response.status_code == 404, response.text

import pytest
from auth_helpers import add_grant, events, make_group, make_server, signed_in
from conftest import owner_session
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.inventory.models import Server, ServerStatus

OWNER = "owner@example.com"
OPERATOR = "otto@example.com"


def body(group_id, name="db-01", **fields) -> dict:
    """A valid registration into the group, each field overridable."""
    return {"name": name, "address": "10.0.0.1", "group_id": str(group_id), "os": "linux", "port": 22} | fields


async def interval_of(server_id) -> int:
    async with SessionLocal() as session:
        return await session.scalar(select(Server.metrics_interval_seconds).where(Server.id == server_id))


async def test_a_registered_interval_is_stored_and_recorded(api, clock):
    staging = await make_group("staging")
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.post("/api/servers", json=body(staging.id, metrics_interval_seconds=2))

    assert response.status_code == 200, response.text
    assert response.json()["metrics_interval_seconds"] == 2
    assert await interval_of(response.json()["id"]) == 2
    (created,) = await events("server.created")
    assert created.change["metrics_interval_seconds"] == {"before": None, "after": 2}


@pytest.mark.parametrize("interval", [0, 11, "x"])
async def test_an_interval_outside_1_to_10_answers_422(api, clock, interval):
    staging = await make_group("staging")
    server = await make_server(staging.id, "db-02")
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        registered = await owner.post("/api/servers", json=body(staging.id, metrics_interval_seconds=interval))
        edited = await owner.patch(f"/api/servers/{server.id}", json={"metrics_interval_seconds": interval})
        nulled = await owner.patch(f"/api/servers/{server.id}", json={"metrics_interval_seconds": None})

    assert registered.status_code == 422, registered.text
    assert edited.status_code == 422, edited.text
    assert nulled.status_code == 422, nulled.text
    assert await interval_of(server.id) == 5
    assert await events("server.created") == []
    assert await events("server.changed") == []


async def test_changing_the_interval_records_server_changed(api, clock):
    staging = await make_group("staging")
    server = await make_server(staging.id, "db-01")
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.patch(f"/api/servers/{server.id}", json={"metrics_interval_seconds": 10})

    assert response.status_code == 200, response.text
    assert response.json()["metrics_interval_seconds"] == 10
    assert await interval_of(server.id) == 10
    (changed,) = await events("server.changed")
    assert changed.change == {"metrics_interval_seconds": {"before": 5, "after": 10}}


async def test_an_operator_cannot_change_the_interval(api, clock):
    staging = await make_group("staging")
    server = await make_server(staging.id, "db-01")
    async with signed_in(api, clock, OPERATOR) as (otto, client):
        await add_grant(otto.id, staging.id, "operator")
        response = await client.patch(f"/api/servers/{server.id}", json={"metrics_interval_seconds": 1})

    assert (response.status_code, response.json()) == (403, {"detail": "forbidden"})
    assert await interval_of(server.id) == 5
    assert await events("server.changed") == []


async def test_monitoring_is_returned_once_the_collector_wrote_it(api, clock):
    staging = await make_group("staging")
    server = await make_server(staging.id, "db-01")
    async with owner_session() as session:
        session.add(ServerStatus(server_id=server.id, state="reachable", reason=None, last_sample_at=func.now()))
        await session.commit()

    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        one = await owner.get(f"/api/servers/{server.id}")
        listed = await owner.get("/api/servers")

    assert one.status_code == 200, one.text
    assert listed.status_code == 200, listed.text
    (in_list,) = listed.json()
    for monitoring in (one.json()["monitoring"], in_list["monitoring"]):
        assert (monitoring["state"], monitoring["reason"]) == ("reachable", None)
        assert monitoring["since"] and monitoring["last_sample_at"]

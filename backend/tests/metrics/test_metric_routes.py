"""GET /api/servers/{id}/metrics and GET /api/metrics/overview: a server's chart series for one range, and the
overview numbers of the asked servers the person sees."""

import uuid
from datetime import UTC, datetime, timedelta

from auth_helpers import add_grant, events, make_group, make_server, signed_in
from conftest import owner_session

from app.metrics.ranges import METRIC_NAMES
from app.metrics.samples import Reading, Sample
from app.metrics.store import TREND_SLOTS, write_samples

OWNER = "owner@example.com"
OPERATOR = "otto@example.com"


async def _write(server_id: uuid.UUID, ago: float, *readings: tuple[str, str, float]) -> None:
    # The routes read up to the real now, so the samples are a few seconds old.
    sample = Sample(
        time=datetime.now(UTC) - timedelta(seconds=ago),
        server_id=server_id,
        readings=tuple(Reading(metric=metric, instance=instance, value=value) for metric, instance, value in readings),
    )
    async with owner_session() as session:
        await write_samples(session, [sample])
        await session.commit()


async def _two_samples(server_id: uuid.UUID) -> None:
    await _write(server_id, 4, ("cpu.used_percent", "", 10.0), ("mem.used_percent", "", 50.0))
    await _write(server_id, 2, ("cpu.used_percent", "", 30.0), ("mem.used_percent", "", 60.0))


async def test_the_series_of_a_visible_server(api, clock):
    server = await make_server((await make_group("staging")).id, "web-1")
    await _two_samples(server.id)
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.get(
            f"/api/servers/{server.id}/metrics",
            params={"range": "live", "metric": ["mem.used_percent", "cpu.used_percent"]},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["range"], body["step_seconds"]) == ("live", None)
    start, end = datetime.fromisoformat(body["start"]), datetime.fromisoformat(body["end"])
    assert end - start == timedelta(minutes=15)
    assert abs(datetime.now(UTC) - end) < timedelta(minutes=1)
    assert [(s["metric"], s["instance"]) for s in body["series"]] == [
        ("cpu.used_percent", ""),
        ("mem.used_percent", ""),
    ]
    cpu, mem = body["series"]
    assert cpu["avg"] == [10.0, 30.0]
    assert mem["avg"] == [50.0, 60.0]
    assert len(cpu["time"]) == 2
    assert cpu["min"] == cpu["max"] == [None, None]


async def test_range_1h_has_a_10_second_step(api, clock):
    server = await make_server((await make_group("staging")).id, "web-1")
    await _two_samples(server.id)
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.get(
            f"/api/servers/{server.id}/metrics", params={"range": "1h", "metric": "cpu.used_percent"}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["range"], body["step_seconds"]) == ("1h", 10)
    [cpu] = body["series"]
    assert cpu["time"]
    assert all(isinstance(value, float) for value in cpu["min"] + cpu["max"])
    assert min(cpu["min"]) == 10.0
    assert max(cpu["max"]) == 30.0


async def test_an_unseen_server_is_404_and_recorded(api, clock):
    staging, production = await make_group("staging"), await make_group("production")
    server = await make_server(production.id, "db-1")
    async with signed_in(api, clock, OPERATOR) as (otto, client):
        await add_grant(otto.id, staging.id, "operator")
        response = await client.get(
            f"/api/servers/{server.id}/metrics", params={"range": "live", "metric": "cpu.used_percent"}
        )

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "not_found"
    [event] = await events("access.denied")
    assert event.result_detail == {"required": "group", "route": "GET /api/servers/{server_id}/metrics"}


async def test_a_missing_server_is_404(api, clock):
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.get(
            f"/api/servers/{uuid.uuid4()}/metrics", params={"range": "live", "metric": "cpu.used_percent"}
        )

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "not_found"


async def test_unknown_range_or_metric_is_422(api, clock):
    server = await make_server((await make_group("staging")).id, "web-1")
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        path = f"/api/servers/{server.id}/metrics"
        bad_range = await owner.get(path, params={"range": "2h", "metric": "cpu.used_percent"})
        bad_metric = await owner.get(path, params={"range": "live", "metric": "cpu.bogus"})
        no_metric = await owner.get(path, params={"range": "live"})

    assert [bad_range.status_code, bad_metric.status_code, no_metric.status_code] == [422, 422, 422]


async def test_at_most_16_metrics(api, clock):
    server = await make_server((await make_group("staging")).id, "web-1")
    names = sorted(METRIC_NAMES)
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        path = f"/api/servers/{server.id}/metrics"
        too_many = await owner.get(path, params={"range": "live", "metric": names[:17]})
        repeated = await owner.get(path, params={"range": "live", "metric": ["cpu.used_percent"] * 16})

    assert too_many.status_code == 422, too_many.text
    assert repeated.status_code == 200, repeated.text


async def test_the_overview_of_visible_servers(api, clock):
    staging, production = await make_group("staging"), await make_group("production")
    s1 = await make_server(staging.id, "web-1")
    p1 = await make_server(production.id, "db-1")
    missing = uuid.uuid4()
    await _write(s1.id, 3, ("cpu.used_percent", "", 25.0), ("mem.used_percent", "", 40.0), ("load.1m", "", 0.5))
    async with signed_in(api, clock, OPERATOR) as (otto, client):
        await add_grant(otto.id, staging.id, "operator")
        before = len(await events("access.denied"))
        response = await client.get(
            "/api/metrics/overview", params={"server_id": [str(s1.id), str(p1.id), str(missing)]}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    [entry] = body["servers"]
    assert entry["server_id"] == str(s1.id)
    assert (entry["cpu"], entry["mem"], entry["load"], entry["disk"]) == (25.0, 40.0, 0.5, None)
    assert entry["time"] is not None
    assert len(entry["trend"]["cpu"]) == len(entry["trend"]["mem"]) == TREND_SLOTS
    assert 25.0 in entry["trend"]["cpu"]
    assert body["denied"] == sorted([str(p1.id), str(missing)])
    recorded = await events("access.denied")
    assert len(recorded) == before + 1
    assert recorded[-1].result_detail == {
        "required": "group",
        "route": "GET /api/metrics/overview",
        "server_ids": [str(p1.id)],
    }


async def test_the_overview_keeps_the_asked_order_once_each(api, clock):
    group = await make_group("staging")
    a, b = await make_server(group.id, "web-1"), await make_server(group.id, "web-2")
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        response = await owner.get("/api/metrics/overview", params={"server_id": [str(b.id), str(a.id), str(b.id)]})

    assert response.status_code == 200, response.text
    body = response.json()
    assert [entry["server_id"] for entry in body["servers"]] == [str(b.id), str(a.id)]
    assert body["servers"][0]["time"] is None
    assert body["denied"] == []


async def test_the_overview_without_hidden_servers_records_nothing(api, clock):
    staging = await make_group("staging")
    s1 = await make_server(staging.id, "web-1")
    async with signed_in(api, clock, OPERATOR) as (otto, client):
        await add_grant(otto.id, staging.id, "operator")
        response = await client.get("/api/metrics/overview", params={"server_id": [str(s1.id), str(uuid.uuid4())]})

    assert response.status_code == 200, response.text
    assert len(response.json()["denied"]) == 1
    assert await events("access.denied") == []


async def test_at_most_200_servers(api, clock):
    async with signed_in(api, clock, OWNER, "owner") as (_, owner):
        ids = [str(uuid.uuid4()) for _ in range(201)]
        too_many = await owner.get("/api/metrics/overview", params={"server_id": ids})
        none = await owner.get("/api/metrics/overview")

    assert too_many.status_code == 422, too_many.text
    assert none.status_code == 422, none.text


async def test_signed_out_is_401(api):
    params = {"range": "live", "metric": "cpu.used_percent"}
    series = await api.get(f"/api/servers/{uuid.uuid4()}/metrics", params=params)
    overview = await api.get("/api/metrics/overview", params={"server_id": str(uuid.uuid4())})

    assert (series.status_code, overview.status_code) == (401, 401)

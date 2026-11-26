from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alerts_helpers import make_rule, starter_rules
from auth_helpers import add_grant, events, make_group, make_server, signed_in

from app.alerts.models import Alert
from conftest import owner_session

pytestmark = pytest.mark.usefixtures("clean_alerts")

RULE = {
    "name": "Disk full",
    "metric": "disk.used_percent",
    "comparison": "above",
    "threshold": 90,
    "duration_seconds": 600,
    "severity": "critical",
}


async def firing(rule, server, instance: str = "/", state: str = "firing") -> None:
    """An alert of the rule on the server, as the collector writes it."""
    async with owner_session() as session:
        session.add(
            Alert(
                server_id=server.id,
                rule_id=rule.id,
                rule_name=rule.name,
                metric=rule.metric,
                comparison=rule.comparison,
                threshold=rule.threshold,
                duration_seconds=rule.duration_seconds,
                severity=rule.severity,
                instance=instance,
                state=state,
                end_reason=None,
                fired_at=datetime(2026, 11, 23, 11, 0, tzinfo=UTC),
                resolved_at=None if state == "firing" else datetime(2026, 11, 23, 11, 5, tzinfo=UTC),
            )
        )
        await session.commit()


async def test_the_owner_lists_the_starter_set_with_firing_counts(api, clock):
    disk, memory, _, unreachable = await starter_rules()
    group = await make_group("staging")
    web = await make_server(group.id, "web-01")
    db = await make_server(group.id, "db-01")
    await firing(disk, web, "/")
    await firing(disk, web, "/var")
    await firing(disk, db, "/")
    await firing(memory, db, "", state="resolved")
    await firing(unreachable, web, "")
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, owner_client):
        response = await owner_client.get("/api/alert-rules")

    assert response.status_code == 200, response.text
    rules = response.json()
    assert [(r["name"], r["firing_count"]) for r in rules] == [
        ("CPU busy", 0),
        ("Filesystem almost full", 3),
        ("Memory almost full", 0),
        ("Server unreachable", 1),
    ]
    cpu = rules[0]
    assert {key: cpu[key] for key in RULE} == {
        "name": "CPU busy",
        "metric": "cpu.used_percent",
        "comparison": "above",
        "threshold": 90,
        "duration_seconds": 900,
        "severity": "warning",
    }
    assert (cpu["server_group_id"], cpu["server_group_name"], cpu["server_id"], cpu["server_name"]) == (
        None,
        None,
        None,
        None,
    )
    assert (cpu["enabled"], cpu["revision"], cpu["suggested_playbook_id"]) == (True, 1, None)
    assert cpu["created_at"] and cpu["updated_at"]
    assert (rules[3]["comparison"], rules[3]["threshold"]) == (None, None)


async def test_the_owner_creates_a_rule_for_a_group_or_a_server(api, clock):
    group = await make_group("staging")
    server = await make_server(group.id, "web-01")
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, owner_client):
        for_group = await owner_client.post(
            "/api/alert-rules", json=RULE | {"name": "  Staging disk ", "server_group_id": str(group.id)}
        )
        for_server = await owner_client.post(
            "/api/alert-rules",
            json={"name": "Web down", "metric": "unreachable", "duration_seconds": 0, "severity": "warning"}
            | {"server_id": str(server.id), "enabled": False},
        )

    assert for_group.status_code == 200, for_group.text
    body = for_group.json()
    assert (body["name"], body["server_group_id"], body["server_group_name"]) == (
        "Staging disk",
        str(group.id),
        "staging",
    )
    assert (body["revision"], body["firing_count"], body["enabled"]) == (1, 0, True)
    assert for_server.status_code == 200, for_server.text
    body = for_server.json()
    assert (body["server_id"], body["server_name"], body["comparison"], body["threshold"]) == (
        str(server.id),
        "web-01",
        None,
        None,
    )
    assert body["enabled"] is False


@pytest.mark.parametrize(
    ("fields", "detail"),
    [
        ({"metric": "unreachable", "comparison": None, "threshold": 50}, "bad_threshold"),
        ({"metric": "unreachable", "comparison": "above", "threshold": None}, "bad_threshold"),
        ({"threshold": 100.5}, "bad_threshold"),
        ({"threshold": -1}, "bad_threshold"),
        ({"metric": "load.5m", "threshold": 1001}, "bad_threshold"),
        ({"comparison": None}, "bad_threshold"),
        ({"threshold": None}, "bad_threshold"),
        ({"server_group_id": "GROUP", "server_id": "SERVER"}, "bad_scope"),
        ({"server_group_id": "MISSING"}, "unknown_group"),
        ({"server_id": "MISSING"}, "unknown_server"),
    ],
)
async def test_create_validates_per_metric(api, clock, fields, detail):
    group = await make_group("staging")
    server = await make_server(group.id, "web-01")
    ids = {"GROUP": str(group.id), "SERVER": str(server.id), "MISSING": str(uuid4())}
    body = RULE | {key: ids.get(value, value) if isinstance(value, str) else value for key, value in fields.items()}
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, owner_client):
        response = await owner_client.post("/api/alert-rules", json=body)
        # The highest load and the highest percentage are allowed.
        load = await owner_client.post(
            "/api/alert-rules", json=RULE | {"name": "Load", "metric": "load.15m", "threshold": 1000}
        )
        percent = await owner_client.post("/api/alert-rules", json=RULE | {"name": "Full", "threshold": 100})

    assert (response.status_code, response.json()) == (422, {"detail": detail})
    assert (load.status_code, percent.status_code) == (200, 200)
    assert [e.target_name for e in await events("alert_rule.created")] == ["Load", "Full"]


async def test_a_patch_is_validated_as_the_rule_it_makes(api, clock):
    rule = await make_rule(**RULE)
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, owner_client):
        to_unreachable = await owner_client.patch(f"/api/alert-rules/{rule.id}", json={"metric": "unreachable"})
        to_load = await owner_client.patch(f"/api/alert-rules/{rule.id}", json={"metric": "load.1m", "threshold": 2})
        unknown = await owner_client.patch(f"/api/alert-rules/{uuid4()}", json={"name": "Other"})

    assert (to_unreachable.status_code, to_unreachable.json()) == (422, {"detail": "bad_threshold"})
    assert to_load.status_code == 200, to_load.text
    assert (to_load.json()["metric"], to_load.json()["threshold"]) == ("load.1m", 2)
    assert (unknown.status_code, unknown.json()) == (404, {"detail": "not_found"})


async def test_a_name_is_unique_without_regard_to_case(api, clock):
    await make_rule(**RULE)
    other = await make_rule(**RULE | {"name": "Memory"})
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, owner_client):
        created = await owner_client.post("/api/alert-rules", json=RULE | {"name": "DISK FULL"})
        renamed = await owner_client.patch(f"/api/alert-rules/{other.id}", json={"name": "disk full"})

    assert (created.status_code, created.json()) == (409, {"detail": "rule_name_taken"})
    assert (renamed.status_code, renamed.json()) == (409, {"detail": "rule_name_taken"})
    assert await events("alert_rule.created") == []
    assert await events("alert_rule.changed") == []


async def test_patch_raises_the_revision_only_for_the_condition_scope_or_severity(api, clock):
    rule = await make_rule(**RULE)
    group = await make_group("staging")
    server = await make_server(group.id, "web-01")
    steps = [
        ({"name": "Renamed"}, 1),
        ({"enabled": False}, 1),
        ({"threshold": 95}, 2),
        ({"comparison": "below"}, 3),
        ({"duration_seconds": 0}, 4),
        ({"severity": "warning"}, 5),
        ({"server_group_id": str(group.id)}, 6),
        ({"server_group_id": None, "server_id": str(server.id)}, 7),
        ({"metric": "disk.inodes_used_percent", "enabled": True}, 8),
    ]
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, owner_client):
        for body, revision in steps:
            response = await owner_client.patch(f"/api/alert-rules/{rule.id}", json=body)
            assert response.status_code == 200, (body, response.text)
            assert response.json()["revision"] == revision, body
        same = [
            await owner_client.patch(f"/api/alert-rules/{rule.id}", json=body)
            for body in ({}, {"name": " Renamed ", "threshold": 95.0}, {"server_id": str(server.id)})
        ]

    final = response.json()
    assert {key: final[key] for key in RULE} == {
        "name": "Renamed",
        "metric": "disk.inodes_used_percent",
        "comparison": "below",
        "threshold": 95,
        "duration_seconds": 0,
        "severity": "warning",
    }
    assert (final["server_group_id"], final["server_id"], final["server_name"]) == (None, str(server.id), "web-01")
    assert datetime.fromisoformat(final["updated_at"]) > datetime.fromisoformat(final["created_at"])
    assert [(r.status_code, r.json()) for r in same] == [(409, {"detail": "no_change"})] * 3
    assert len(await events("alert_rule.changed")) == len(steps)


async def test_each_change_is_audited_with_the_threshold_as_text(api, clock):
    async with signed_in(api, clock, "owner@example.com", "owner") as (owner, owner_client):
        created = await owner_client.post("/api/alert-rules", json=RULE)
        rule_id = created.json()["id"]
        changed = await owner_client.patch(f"/api/alert-rules/{rule_id}", json={"name": "Disk", "threshold": 92.5})
        deleted = await owner_client.delete(f"/api/alert-rules/{rule_id}")
        listed = await owner_client.get("/api/alert-rules")
        again = await owner_client.delete(f"/api/alert-rules/{rule_id}")

    assert (created.status_code, changed.status_code, deleted.status_code) == (200, 200, 204)
    assert listed.json() == []
    assert (again.status_code, again.json()) == (404, {"detail": "not_found"})
    (create_event,) = await events("alert_rule.created")
    (change_event,) = await events("alert_rule.changed")
    (delete_event,) = await events("alert_rule.deleted")
    for event, name in ((create_event, "Disk full"), (change_event, "Disk"), (delete_event, "Disk")):
        assert (event.actor_id, event.result, event.mfa) == (str(owner.id), "success", True)
        assert (event.target_type, event.target_id, event.target_name) == ("alert_rule", rule_id, name)
    assert create_event.change == {
        "name": {"before": None, "after": "Disk full"},
        "metric": {"before": None, "after": "disk.used_percent"},
        "comparison": {"before": None, "after": "above"},
        "threshold": {"before": None, "after": "90"},
        "duration_seconds": {"before": None, "after": 600},
        "severity": {"before": None, "after": "critical"},
        "enabled": {"before": None, "after": True},
    }
    assert change_event.change == {
        "name": {"before": "Disk full", "after": "Disk"},
        "threshold": {"before": "90", "after": "92.5"},
    }
    assert delete_event.change["threshold"] == {"before": "92.5", "after": None}
    assert delete_event.change["name"] == {"before": "Disk", "after": None}


async def test_others_get_403_and_access_denied(api, clock):
    rule = await make_rule(**RULE)
    group = await make_group("staging")
    async with (
        signed_in(api, clock, "ada@example.com") as (ada, admin_client),
        signed_in(api, clock, "aud@example.com", "auditor") as (auditor, auditor_client),
    ):
        await add_grant(ada.id, group.id, "admin")
        answers = []
        for client in (admin_client, auditor_client):
            answers += [
                await client.get("/api/alert-rules"),
                await client.post("/api/alert-rules", json=RULE | {"name": "Other"}),
                await client.patch(f"/api/alert-rules/{rule.id}", json={"threshold": 10}),
                await client.delete(f"/api/alert-rules/{rule.id}"),
            ]

    assert [(r.status_code, r.json()) for r in answers] == [(403, {"detail": "forbidden"})] * 8
    routes = [
        "GET /api/alert-rules",
        "POST /api/alert-rules",
        "PATCH /api/alert-rules/{rule_id}",
        "DELETE /api/alert-rules/{rule_id}",
    ]
    denied = await events("access.denied")
    assert [(e.actor_id, e.result, e.result_detail) for e in denied] == [
        (str(person.id), "failure", {"required": "owner", "route": route})
        for person in (ada, auditor)
        for route in routes
    ]
    assert [e for action in ("created", "changed", "deleted") for e in await events(f"alert_rule.{action}")] == []

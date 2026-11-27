from datetime import timedelta

import pytest
from alerts_helpers import make_alert, make_rule
from auth_helpers import add_grant, make_group, make_server, signed_in
from sqlalchemy import delete

from app.access.models import RoleGrant
from conftest import owner_session

pytestmark = pytest.mark.usefixtures("clean_alerts")


def names(response) -> list[tuple[str, str]]:
    assert response.status_code == 200, response.text
    return [(alert["server_name"], alert["state"]) for alert in response.json()]


async def closed(server, clock, minutes_ago: float, **fields):
    """An alert of the server that resolved `minutes_ago`, after firing an hour before."""
    resolved_at = clock.now - timedelta(minutes=minutes_ago)
    return await make_alert(
        server.id,
        state=fields.pop("state", "resolved"),
        fired_at=resolved_at - timedelta(hours=1),
        resolved_at=resolved_at,
        **fields,
    )


async def test_a_person_sees_only_alerts_of_servers_they_see(api, clock):
    seen, hidden = await make_group("staging"), await make_group("production")
    web, db = await make_server(seen.id, "web-01"), await make_server(hidden.id, "db-01")
    rule = await make_rule(name="Disk full", threshold=90, duration_seconds=600)
    fired_at = clock.now - timedelta(minutes=20)
    fired = await make_alert(web.id, fired_at=fired_at, rule=rule, instance="/var")
    await make_alert(db.id, fired_at=clock.now - timedelta(minutes=10))
    await closed(web, clock, 30)
    await closed(db, clock, 40, state="ended")
    async with (
        signed_in(api, clock, "owner@example.com", "owner") as (_, owner),
        signed_in(api, clock, "ops@example.com") as (operator, client),
    ):
        await add_grant(operator.id, seen.id, "operator")

        assert names(await owner.get("/api/alerts")) == [("db-01", "firing"), ("web-01", "firing")]
        assert names(await owner.get("/api/alerts", params={"state": "closed"})) == [
            ("web-01", "resolved"),
            ("db-01", "ended"),
        ]
        response = await client.get("/api/alerts")
        assert names(response) == [("web-01", "firing")]
        assert names(await client.get("/api/alerts", params={"state": "closed"})) == [("web-01", "resolved")]

    assert response.json()[0] == {
        "id": str(fired.id),
        "server_id": str(web.id),
        "server_name": "web-01",
        "group_id": str(seen.id),
        "group_name": "staging",
        "rule_id": str(rule.id),
        "rule_name": "Disk full",
        "metric": "disk.used_percent",
        "comparison": "above",
        "threshold": 90.0,
        "duration_seconds": 600,
        "severity": "critical",
        "instance": "/var",
        "state": "firing",
        "end_reason": None,
        "fired_at": fired_at.isoformat().replace("+00:00", "Z"),
        "resolved_at": None,
        "value": 93.4,
        "last_value": 93.4,
        "peak_value": 95.0,
    }


async def test_firing_and_closed_follow_the_group_and_tag_filters(api, clock):
    first, second = await make_group("staging"), await make_group("production")
    a1 = await make_server(first.id, "a1", tags=("prod", "web"))
    a2 = await make_server(first.id, "a2", tags=("dev",))
    b1 = await make_server(second.id, "b1", tags=("prod",))
    for minutes, server in enumerate((a1, a2, b1), start=1):
        await make_alert(server.id, fired_at=clock.now - timedelta(minutes=minutes))
        await closed(server, clock, minutes)
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, client):
        for state in ("firing", "closed"):
            by_group = await client.get("/api/alerts", params={"state": state, "group_id": str(first.id)})
            by_tag = await client.get("/api/alerts", params={"state": state, "tag": "prod"})
            both = await client.get("/api/alerts", params={"state": state, "group_id": str(first.id), "tag": " PROD "})
            two_tags = await client.get("/api/alerts", params={"state": state, "tag": ["prod", "web"]})

            assert [name for name, _ in names(by_group)] == ["a1", "a2"]
            assert [name for name, _ in names(by_tag)] == ["a1", "b1"]
            assert [name for name, _ in names(both)] == ["a1"]
            assert [name for name, _ in names(two_tags)] == ["a1"]

        assert (await client.get("/api/alerts", params={"state": "open"})).status_code == 422


async def test_closed_is_newest_first_50_per_page_within_30_days_and_pages_with_before(api, clock):
    group = await make_group("staging")
    web = await make_server(group.id, "web-01")
    await make_alert(web.id, fired_at=clock.now - timedelta(days=2))
    recent = [await closed(web, clock, minutes, instance=f"/m{minutes}") for minutes in range(1, 55)]
    recent.append(await closed(web, clock, 60 * 24 * 29, state="ended"))
    await closed(web, clock, 60 * 24 * 31)
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, client):
        page = await client.get("/api/alerts", params={"state": "closed"})
        assert page.status_code == 200, page.text
        first = page.json()
        last = first[-1]["resolved_at"]
        rest = (await client.get("/api/alerts", params={"state": "closed", "before": last})).json()
        short = (await client.get("/api/alerts", params={"state": "closed", "limit": 10})).json()
        too_many = await client.get("/api/alerts", params={"state": "closed", "limit": 51})
        none = await client.get("/api/alerts", params={"state": "closed", "limit": 0})

    assert [alert["id"] for alert in first] == [str(alert.id) for alert in recent[:50]]
    assert [alert["id"] for alert in rest] == [str(alert.id) for alert in recent[50:]]
    assert rest[-1]["state"] == "ended" and rest[-1]["end_reason"] == "rule_changed"
    assert [alert["id"] for alert in short] == [str(alert.id) for alert in recent[:10]]
    assert (too_many.status_code, none.status_code) == (422, 422)


async def test_the_server_route_lists_firing_first_then_history_and_404s_a_hidden_server(api, clock):
    seen, hidden = await make_group("staging"), await make_group("production")
    web, db = await make_server(seen.id, "web-01"), await make_server(hidden.id, "db-01")
    older = await make_alert(web.id, fired_at=clock.now - timedelta(hours=3), instance="/")
    newer = await make_alert(web.id, fired_at=clock.now - timedelta(hours=1), instance="/var")
    history = [await closed(web, clock, minutes, instance=f"/m{minutes}") for minutes in range(1, 52)]
    history.append(await closed(web, clock, 60 * 24 * 40))
    await make_alert(db.id, fired_at=clock.now - timedelta(minutes=5))
    await closed(db, clock, 5)
    async with signed_in(api, clock, "ops@example.com") as (operator, client):
        await add_grant(operator.id, seen.id, "operator")
        page = await client.get(f"/api/servers/{web.id}/alerts")
        assert page.status_code == 200, page.text
        first = page.json()
        last = first[-1]["resolved_at"]
        rest = (await client.get(f"/api/servers/{web.id}/alerts", params={"before": last})).json()
        hidden_server = await client.get(f"/api/servers/{db.id}/alerts")

    assert [alert["id"] for alert in first] == [str(newer.id), str(older.id)] + [str(a.id) for a in history[:50]]
    assert [alert["id"] for alert in rest] == [str(alert.id) for alert in history[50:]]
    assert hidden_server.status_code == 404


async def test_alerts_closed_at_the_same_time_page_with_before_and_before_id(api, clock):
    """The collector ends every alert of a deleted rule with one `now`: no page may skip some of them."""
    group = await make_group("staging")
    web = await make_server(group.id, "web-01")
    together = [await closed(web, clock, 5, state="ended", instance=f"/m{n}") for n in range(53)]
    together.sort(key=lambda alert: alert.id, reverse=True)
    older = await closed(web, clock, 10)
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, client):
        pages = []
        for path, extra in ((f"/api/servers/{web.id}/alerts", {}), ("/api/alerts", {"state": "closed"})):
            first = (await client.get(path, params=extra)).json()
            cursor = {"before": first[-1]["resolved_at"], "before_id": first[-1]["id"]}
            rest = (await client.get(path, params={**extra, **cursor})).json()
            pages.append((first, rest))
        short = (await client.get(f"/api/servers/{web.id}/alerts", params={"limit": 10})).json()
        too_many = await client.get(f"/api/servers/{web.id}/alerts", params={"limit": 51})

    expected = [str(alert.id) for alert in together] + [str(older.id)]
    for first, rest in pages:
        assert [alert["id"] for alert in first + rest] == expected
    assert [alert["id"] for alert in short] == expected[:10]
    assert too_many.status_code == 422


async def test_the_bell_counts_unseen_events_and_seen_moves_the_mark(api, clock):
    group = await make_group("staging")
    web = await make_server(group.id, "web-01")
    await closed(web, clock, 60 * 24 * 31, kind_events=("fired", "resolved"))
    for minutes in range(5, 0, -1):
        await closed(web, clock, 90 * minutes, instance=f"/m{minutes}", kind_events=("fired", "resolved"))
    fired_at = clock.now - timedelta(minutes=10)
    firing = await make_alert(web.id, fired_at=fired_at)
    async with signed_in(api, clock, "ops@example.com") as (operator, client):
        await add_grant(operator.id, group.id, "operator")
        before = await client.get("/api/alerts/events")
        seen = await client.post("/api/alerts/seen")
        after = (await client.get("/api/alerts/events")).json()
        clock.advance(minutes=1)
        await make_alert(web.id, fired_at=clock.now, instance="/new")
        later = (await client.get("/api/alerts/events")).json()

    assert before.status_code == 200, before.text
    bell = before.json()
    assert (bell["unseen"], bell["firing"], len(bell["events"])) == (11, 1, 10)
    latest = bell["events"][0]
    assert (latest["kind"], latest["alert"]["id"], latest["alert"]["server_name"]) == ("fired", str(firing.id), "web-01")
    assert latest["at"] == fired_at.isoformat().replace("+00:00", "Z")
    assert [event["kind"] for event in bell["events"][1:3]] == ["resolved", "fired"]
    ats = [event["at"] for event in bell["events"]]
    assert ats == sorted(ats, reverse=True)
    assert seen.status_code == 204
    assert (after["unseen"], after["firing"], len(after["events"])) == (0, 1, 10)
    assert (later["unseen"], later["firing"], later["events"][0]["alert"]["instance"]) == (1, 2, "/new")


async def test_a_person_who_loses_sight_of_a_server_loses_its_events(api, clock):
    group = await make_group("staging")
    web = await make_server(group.id, "web-01")
    await make_alert(web.id, fired_at=clock.now - timedelta(minutes=10))
    async with signed_in(api, clock, "ops@example.com") as (operator, client):
        await add_grant(operator.id, group.id, "operator")
        bell = (await client.get("/api/alerts/events")).json()
        assert (bell["unseen"], bell["firing"], len(bell["events"])) == (1, 1, 1)
        assert len((await client.get("/api/alerts")).json()) == 1

        async with owner_session() as session:
            await session.execute(delete(RoleGrant).where(RoleGrant.user_id == operator.id))
            await session.commit()
        bell = (await client.get("/api/alerts/events")).json()
        listed = await client.get("/api/alerts")
        server = await client.get(f"/api/servers/{web.id}/alerts")

    assert bell == {"unseen": 0, "firing": 0, "events": []}
    assert listed.json() == []
    assert server.status_code == 404

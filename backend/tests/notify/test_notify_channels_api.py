import json
from datetime import UTC, datetime, timedelta

import pytest
from alerts_helpers import events_of, make_alert, make_channel, make_rule
from auth_helpers import add_grant, events, make_group, make_server, signed_in
from sinks import HttpSink
from sqlalchemy import select

from app.core.config import get_settings
from app.notify import transports
from app.notify.crypto import unseal
from app.notify.messages import TEST_TEXT
from app.notify.models import NotificationChannel, NotificationDelivery
from conftest import owner_session

pytestmark = pytest.mark.usefixtures("clean_alerts")

TOKEN = "123456:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789_-"
SLACK = {"name": "Ops Slack", "kind": "webhook_slack", "url": "https://hooks.slack.com/services/T0/B0/x9Q"}
TELEGRAM = {"name": "On call", "kind": "telegram", "bot_token": TOKEN, "chat_id": "-100123"}


@pytest.fixture
def allow_http(monkeypatch):
    settings = get_settings().model_copy(update={"webhook_allow_http": True})
    monkeypatch.setattr("app.notify.service.get_settings", lambda: settings)


async def saved_channels() -> list[NotificationChannel]:
    async with owner_session() as session:
        return list((await session.scalars(select(NotificationChannel).order_by(NotificationChannel.name))).all())


def secret_of(channel: NotificationChannel) -> dict:
    return json.loads(unseal(channel.secret, channel.id.bytes))


async def test_create_list_patch_delete_with_their_events(api, clock):
    async with signed_in(api, clock, "owner@example.com", "owner") as (owner, client):
        created = await client.post("/api/notification-channels", json=SLACK)
        channel_id = created.json()["id"]
        listed = await client.get("/api/notification-channels")
        renamed = await client.patch(
            f"/api/notification-channels/{channel_id}", json={"name": "Slack", "min_severity": "critical"}
        )
        new_url = await client.patch(
            f"/api/notification-channels/{channel_id}", json={"url": "https://chat.example.com/hook/abc"}
        )
        [saved] = await saved_channels()
        deleted = await client.delete(f"/api/notification-channels/{channel_id}")
        again = await client.delete(f"/api/notification-channels/{channel_id}")
        missing = await client.patch(f"/api/notification-channels/{channel_id}", json={"name": "x"})

    assert created.status_code == 200, created.text
    body = created.json()
    assert {key: body[key] for key in ("name", "kind", "min_severity", "enabled", "hint", "last_delivery")} == {
        "name": "Ops Slack",
        "kind": "webhook_slack",
        "min_severity": "warning",
        "enabled": True,
        "hint": "hooks.slack.com",
        "last_delivery": None,
    }
    assert set(body) == {
        "id", "name", "kind", "min_severity", "enabled", "hint", "created_at", "updated_at", "last_delivery"
    }
    assert listed.json() == [body]
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["name"], renamed.json()["min_severity"]) == ("Slack", "critical")
    assert new_url.json()["hint"] == "chat.example.com"
    assert secret_of(saved) == {"url": "https://chat.example.com/hook/abc"}
    assert deleted.status_code == 204
    assert (again.status_code, missing.status_code) == (404, 404)
    assert await saved_channels() == []

    [made] = await events("notification_channel.created")
    first, second = await events("notification_channel.changed")
    [gone] = await events("notification_channel.deleted")
    assert (made.actor_id, made.target_type, made.target_id, made.target_name) == (
        str(owner.id),
        "notification_channel",
        channel_id,
        "Ops Slack",
    )
    assert made.change == {
        "enabled": {"before": None, "after": True},
        "hint": {"before": None, "after": "hooks.slack.com"},
        "kind": {"before": None, "after": "webhook_slack"},
        "min_severity": {"before": None, "after": "warning"},
        "name": {"before": None, "after": "Ops Slack"},
        "secret": {"before": "[redacted]", "after": "[redacted]"},
    }
    assert first.change == {
        "min_severity": {"before": "warning", "after": "critical"},
        "name": {"before": "Ops Slack", "after": "Slack"},
    }
    assert second.change == {
        "hint": {"before": "hooks.slack.com", "after": "chat.example.com"},
        "secret": {"before": "[redacted]", "after": "[redacted]"},
    }
    assert gone.target_name == "Slack"
    assert gone.change["name"] == {"before": "Slack", "after": None}


async def test_the_hint_is_the_url_host_or_the_chat(api, clock):
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, client):
        webhook = await client.post(
            "/api/notification-channels",
            json={"name": "Generic", "kind": "webhook_json", "url": "https://Hooks.Example.com:8443/x/secret-path"},
        )
        telegram = await client.post("/api/notification-channels", json=TELEGRAM)
        by_name = await client.post(
            "/api/notification-channels", json=TELEGRAM | {"name": "Channel", "chat_id": "@megoo_alerts"}
        )
        chat_only = await client.patch(f"/api/notification-channels/{telegram.json()['id']}", json={"chat_id": "42"})

    assert webhook.json()["hint"] == "hooks.example.com"
    assert telegram.json()["hint"] == "chat -100123"
    assert by_name.json()["hint"] == "chat @megoo_alerts"
    assert chat_only.status_code == 200, chat_only.text
    assert chat_only.json()["hint"] == "chat 42"
    on_call = next(channel for channel in await saved_channels() if channel.name == "On call")
    # Sending the chat alone keeps the bot token.
    assert secret_of(on_call) == {"bot_token": TOKEN, "chat_id": "42"}


async def test_an_http_url_is_refused_unless_webhook_allow_http(api, clock, monkeypatch):
    http = {"name": "Local", "kind": "webhook_json", "url": "http://10.0.0.5/hook"}
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, client):
        refused = await client.post("/api/notification-channels", json=http)
        not_a_url = await client.post("/api/notification-channels", json=http | {"url": "ftp://example.com/x"})
        no_url = await client.post("/api/notification-channels", json={"name": "Local", "kind": "webhook_json"})
        made = await client.post("/api/notification-channels", json=SLACK)
        patched = await client.patch(f"/api/notification-channels/{made.json()['id']}", json={"url": http["url"]})
        settings = get_settings().model_copy(update={"webhook_allow_http": True})
        monkeypatch.setattr("app.notify.service.get_settings", lambda: settings)
        allowed = await client.post("/api/notification-channels", json=http)

    assert (refused.status_code, refused.json()) == (422, {"detail": "webhook_url_https"})
    assert (not_a_url.status_code, not_a_url.json()) == (422, {"detail": "bad_url"})
    assert (no_url.status_code, no_url.json()) == (422, {"detail": "bad_url"})
    assert (patched.status_code, patched.json()) == (422, {"detail": "webhook_url_https"})
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["hint"] == "10.0.0.5"


async def test_bad_telegram_token_and_chat_id(api, clock):
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, client):
        answers = [
            await client.post("/api/notification-channels", json=TELEGRAM | {"bot_token": token})
            for token in ("123:" + "a" * 35, "123456:short", "abcdef:" + "a" * 35, None)
        ]
        chats = [
            await client.post("/api/notification-channels", json=TELEGRAM | {"chat_id": chat})
            for chat in ("12ab", "@abc", "-" + "1" * 21, None)
        ]
        made = await client.post("/api/notification-channels", json=TELEGRAM)
        patched = await client.patch(f"/api/notification-channels/{made.json()['id']}", json={"bot_token": "nope"})

    assert [(r.status_code, r.json()) for r in answers] == [(422, {"detail": "bad_telegram_token"})] * 4
    assert [(r.status_code, r.json()) for r in chats] == [(422, {"detail": "bad_chat_id"})] * 4
    assert (patched.status_code, patched.json()) == (422, {"detail": "bad_telegram_token"})
    [saved] = await saved_channels()
    assert secret_of(saved) == {"bot_token": TOKEN, "chat_id": "-100123"}


async def test_at_most_20_channels(api, clock):
    for n in range(19):
        await make_channel("webhook_json", {"url": f"https://example.com/{n}"}, name=f"Hook {n}")
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, client):
        twentieth = await client.post("/api/notification-channels", json=SLACK)
        too_many = await client.post("/api/notification-channels", json=SLACK | {"name": "One more"})

    assert twentieth.status_code == 200, twentieth.text
    assert (too_many.status_code, too_many.json()) == (409, {"detail": "too_many_channels"})
    assert len(await saved_channels()) == 20
    assert len(await events("notification_channel.created")) == 1


async def test_a_unique_name(api, clock):
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, client):
        await client.post("/api/notification-channels", json=SLACK)
        taken = await client.post("/api/notification-channels", json=TELEGRAM | {"name": "ops slack"})
        other = await client.post("/api/notification-channels", json=TELEGRAM)
        renamed = await client.patch(f"/api/notification-channels/{other.json()['id']}", json={"name": "OPS SLACK"})
        recased = await client.patch(f"/api/notification-channels/{other.json()['id']}", json={"name": "ON CALL"})

    assert (taken.status_code, taken.json()) == (409, {"detail": "channel_name_taken"})
    assert (renamed.status_code, renamed.json()) == (409, {"detail": "channel_name_taken"})
    assert recased.status_code == 200, recased.text
    assert [channel.name for channel in await saved_channels()] == ["ON CALL", "Ops Slack"]


async def test_send_a_test_reaches_the_sink_and_is_audited(api, clock, allow_http, monkeypatch, unused_tcp_port):
    async with HttpSink() as sink:
        monkeypatch.setattr(transports, "TELEGRAM_API", sink.url)
        async with signed_in(api, clock, "owner@example.com", "owner") as (owner, client):
            ids = []
            for body in (
                {"name": "Generic", "kind": "webhook_json", "url": f"{sink.url}/generic"},
                {"name": "Slack", "kind": "webhook_slack", "url": f"{sink.url}/slack"},
                TELEGRAM,
                # Switched off, and nothing listens on its port: a test is sent all the same.
                {"name": "Gone", "kind": "webhook_json", "url": f"http://127.0.0.1:{unused_tcp_port}/x"}
                | {"enabled": False},
            ):
                ids.append((await client.post("/api/notification-channels", json=body)).json()["id"])
            results = [await client.post(f"/api/notification-channels/{channel_id}/test") for channel_id in ids]
            missing = await client.post("/api/notification-channels/00000000-0000-0000-0000-000000000000/test")

    assert [(r.status_code, r.json()) for r in results] == [(200, {"ok": True, "error": None})] * 3 + [
        (200, {"ok": False, "error": "connection_failed"})
    ]
    assert missing.status_code == 404
    assert [(post["path"], json.loads(post["body"])) for post in sink.received] == [
        ("/generic", {"version": 1, "event": "test", "text": TEST_TEXT}),
        ("/slack", {"text": TEST_TEXT}),
        (f"/bot{TOKEN}/sendMessage", {"chat_id": "-100123", "text": TEST_TEXT}),
    ]
    tested = await events("notification_channel.tested")
    assert [(e.actor_id, e.target_id, e.result, e.result_detail) for e in tested] == [
        (str(owner.id), ids[0], "success", {"ok": True, "error": None}),
        (str(owner.id), ids[1], "success", {"ok": True, "error": None}),
        (str(owner.id), ids[2], "success", {"ok": True, "error": None}),
        (str(owner.id), ids[3], "failure", {"ok": False, "error": "connection_failed"}),
    ]


async def test_the_list_shows_the_last_delivery_state(api, clock):
    server = await make_server((await make_group("Production")).id, "db-prod-01")
    rule = await make_rule()
    at = datetime(2026, 11, 26, 12, tzinfo=UTC)
    alert = await make_alert(
        server.id,
        state="resolved",
        fired_at=at,
        resolved_at=at + timedelta(minutes=5),
        rule=rule,
        kind_events=("fired", "resolved"),
    )
    fired, resolved = await events_of(alert.id)
    quiet = await make_channel("webhook_json", {"url": "https://example.com/quiet"}, name="Quiet")
    busy = await make_channel("webhook_json", {"url": "https://example.com/busy"}, name="Busy")
    async with owner_session() as session:
        session.add_all(
            [
                NotificationDelivery(
                    event_id=fired.id,
                    channel_id=busy.id,
                    state="delivered",
                    attempts=1,
                    next_attempt_at=at,
                    delivered_at=at + timedelta(seconds=2),
                    created_at=at,
                ),
                NotificationDelivery(
                    event_id=resolved.id,
                    channel_id=busy.id,
                    state="failed",
                    attempts=6,
                    next_attempt_at=at + timedelta(hours=1),
                    last_error="http_status",
                    created_at=at + timedelta(minutes=5),
                ),
                # The email's delivery is not a channel's.
                NotificationDelivery(
                    event_id=resolved.id, channel_id=None, state="pending", next_attempt_at=at, created_at=at
                ),
            ]
        )
        await session.commit()
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, client):
        listed = await client.get("/api/notification-channels")

    assert listed.status_code == 200, listed.text
    assert [(c["name"], c["last_delivery"]) for c in listed.json()] == [
        ("Busy", {"state": "failed", "at": "2026-11-26T13:00:00Z", "error": "http_status"}),
        ("Quiet", None),
    ]
    assert {c["id"] for c in listed.json()} == {str(busy.id), str(quiet.id)}


async def test_others_get_403(api, clock):
    group = await make_group("staging")
    channel = await make_channel("webhook_slack", {"url": "https://hooks.slack.com/x"}, name="Slack")
    async with (
        signed_in(api, clock, "ada@example.com") as (ada, admin_client),
        signed_in(api, clock, "aud@example.com", "auditor") as (auditor, auditor_client),
    ):
        await add_grant(ada.id, group.id, "admin")
        answers = []
        for client in (admin_client, auditor_client):
            answers += [
                await client.get("/api/notification-channels"),
                await client.post("/api/notification-channels", json=SLACK),
                await client.patch(f"/api/notification-channels/{channel.id}", json={"name": "Mine"}),
                await client.delete(f"/api/notification-channels/{channel.id}"),
                await client.post(f"/api/notification-channels/{channel.id}/test"),
            ]

    assert [(r.status_code, r.json()) for r in answers] == [(403, {"detail": "forbidden"})] * 10
    routes = [
        "GET /api/notification-channels",
        "POST /api/notification-channels",
        "PATCH /api/notification-channels/{channel_id}",
        "DELETE /api/notification-channels/{channel_id}",
        "POST /api/notification-channels/{channel_id}/test",
    ]
    denied = await events("access.denied")
    assert [(e.actor_id, e.result_detail) for e in denied] == [
        (str(person.id), {"required": "owner", "route": route}) for person in (ada, auditor) for route in routes
    ]
    assert [c.name for c in await saved_channels()] == ["Slack"]
    actions = ("created", "changed", "deleted", "tested")
    assert [e for action in actions for e in await events(f"notification_channel.{action}")] == []

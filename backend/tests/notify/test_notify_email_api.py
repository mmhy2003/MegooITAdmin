import pytest
from auth_helpers import add_grant, events, make_group, signed_in
from sinks import SmtpSink
from sqlalchemy import select

from app.notify.crypto import EMAIL_ROW, unseal
from app.notify.messages import TEST_TEXT
from app.notify.models import NotificationEmail
from conftest import owner_session

pytestmark = pytest.mark.usefixtures("clean_alerts")

EMAIL = {
    "enabled": True,
    "host": "smtp.example.com",
    "port": 587,
    "security": "starttls",
    "username": "alerts",
    "password": "hunter2-smtp",
    "from_name": "MegooITAdmin",
    "from_address": "alerts@example.com",
    "extra_addresses": [],
    "min_severity": "warning",
}


async def saved() -> NotificationEmail:
    async with owner_session() as session:
        return await session.scalar(select(NotificationEmail).where(NotificationEmail.id == 1))


async def saved_password() -> str | None:
    email = await saved()
    return None if email.password is None else unseal(email.password, EMAIL_ROW)


async def test_get_shows_password_set_but_never_the_password(api, clock):
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, client):
        before = await client.get("/api/notifications/email")
        put = await client.put("/api/notifications/email", json=EMAIL)
        after = await client.get("/api/notifications/email")

    assert before.status_code == 200, before.text
    assert before.json() == {
        "enabled": False,
        "host": None,
        "port": 587,
        "security": "starttls",
        "username": None,
        "password_set": False,
        "from_name": "MegooITAdmin",
        "from_address": None,
        "extra_addresses": [],
        "min_severity": "warning",
        "last_delivery": None,
    }
    assert put.status_code == 200, put.text
    assert after.json() == put.json()
    assert after.json() == {key: value for key, value in EMAIL.items() if key != "password"} | {
        "password_set": True,
        "last_delivery": None,
    }
    assert "hunter2-smtp" not in put.text + after.text


async def test_put_keeps_replaces_or_removes_the_password(api, clock):
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, client):
        await client.put("/api/notifications/email", json=EMAIL)
        omitted = {key: value for key, value in EMAIL.items() if key != "password"}
        assert (await client.put("/api/notifications/email", json=omitted | {"port": 2525})).status_code == 200
        kept_when_omitted = await saved_password()
        assert (await client.put("/api/notifications/email", json=EMAIL | {"password": None})).status_code == 200
        kept_when_null = await saved_password()
        replaced = await client.put("/api/notifications/email", json=EMAIL | {"password": "new-one"})
        replaced_with = await saved_password()
        removed = await client.put("/api/notifications/email", json=EMAIL | {"password": ""})

    assert (kept_when_omitted, kept_when_null, replaced_with) == ("hunter2-smtp", "hunter2-smtp", "new-one")
    assert replaced.json()["password_set"] is True
    assert removed.json()["password_set"] is False
    assert (await saved()).password is None


async def test_put_is_audited_with_the_password_redacted(api, clock):
    async with signed_in(api, clock, "owner@example.com", "owner") as (owner, client):
        await client.put("/api/notifications/email", json=EMAIL)
        await client.put("/api/notifications/email", json=EMAIL | {"password": "new-one", "port": 465})
        await client.put("/api/notifications/email", json=EMAIL | {"password": None, "port": 465})

    first, second, third = await events("notification_email.changed")
    assert (first.actor_id, first.result, first.target_type) == (str(owner.id), "success", "notification_email")
    assert first.change["host"] == {"before": None, "after": "smtp.example.com"}
    assert first.change["enabled"] == {"before": False, "after": True}
    assert first.change["password"] == {"before": "[redacted]", "after": "[redacted]"}
    assert second.change == {
        "password": {"before": "[redacted]", "after": "[redacted]"},
        "port": {"before": 587, "after": 465},
    }
    assert third.change is None
    for event in (first, second, third):
        assert "hunter2-smtp" not in str(event.change) and "new-one" not in str(event.change)


async def test_enabling_needs_a_host_and_a_from_address(api, clock):
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, client):
        no_host = await client.put("/api/notifications/email", json=EMAIL | {"host": None})
        blank_host = await client.put("/api/notifications/email", json=EMAIL | {"host": "  "})
        no_from = await client.put("/api/notifications/email", json=EMAIL | {"from_address": None})
        switched_off = await client.put("/api/notifications/email", json=EMAIL | {"enabled": False, "host": None})

    assert [r.status_code for r in (no_host, blank_host, no_from)] == [422] * 3
    assert switched_off.status_code == 200, switched_off.text
    assert len(await events("notification_email.changed")) == 1


async def test_extra_addresses_are_lowercased_deduplicated_and_at_most_20(api, clock):
    twenty = [f"Person{n}@Example.com" for n in range(20)]
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, client):
        addresses = [" Ops@Example.com", "ops@example.com"] + twenty[:19]
        response = await client.put("/api/notifications/email", json=EMAIL | {"extra_addresses": addresses})
        too_many = await client.put(
            "/api/notifications/email", json=EMAIL | {"extra_addresses": twenty + ["x@example.com"]}
        )
        not_an_address = await client.put("/api/notifications/email", json=EMAIL | {"extra_addresses": ["nobody"]})

    assert response.status_code == 200, response.text
    assert response.json()["extra_addresses"] == ["ops@example.com"] + [a.lower() for a in twenty[:19]]
    assert (await saved()).extra_addresses == response.json()["extra_addresses"]
    assert (too_many.status_code, not_an_address.status_code) == (422, 422)


async def test_the_test_goes_to_the_owners_own_address_and_is_audited(api, clock):
    async with SmtpSink() as sink:
        settings = EMAIL | {"host": "127.0.0.1", "port": sink.port, "security": "none", "username": None}
        async with signed_in(api, clock, "owner@example.com", "owner") as (owner, client):
            await client.put("/api/notifications/email", json=settings | {"extra_addresses": ["ops@example.com"]})
            sent = await client.post("/api/notifications/email/test")
            # Nothing listens on the port any more.
            await client.put("/api/notifications/email", json=settings | {"port": 1})
            failed = await client.post("/api/notifications/email/test")

    assert sent.status_code == 200, sent.text
    assert sent.json() == {"ok": True, "error": None}
    assert [(mail["from"], mail["to"]) for mail in sink.mail] == [("alerts@example.com", ["owner@example.com"])]
    assert TEST_TEXT in sink.mail[0]["data"]
    assert failed.status_code == 200, failed.text
    assert failed.json() == {"ok": False, "error": "connection_failed"}
    tested = await events("notification_email.tested")
    assert [(e.actor_id, e.result, e.result_detail) for e in tested] == [
        (str(owner.id), "success", {"ok": True, "error": None}),
        (str(owner.id), "failure", {"ok": False, "error": "connection_failed"}),
    ]


async def test_testing_before_setup_is_409_email_not_set_up(api, clock):
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, client):
        response = await client.post("/api/notifications/email/test")

    assert (response.status_code, response.json()) == (409, {"detail": "email_not_set_up"})
    assert await events("notification_email.tested") == []


async def test_others_get_403(api, clock):
    group = await make_group("staging")
    async with (
        signed_in(api, clock, "ada@example.com") as (ada, admin_client),
        signed_in(api, clock, "aud@example.com", "auditor") as (auditor, auditor_client),
    ):
        await add_grant(ada.id, group.id, "admin")
        answers = []
        for client in (admin_client, auditor_client):
            answers += [
                await client.get("/api/notifications/email"),
                await client.put("/api/notifications/email", json=EMAIL),
                await client.post("/api/notifications/email/test"),
            ]

    assert [(r.status_code, r.json()) for r in answers] == [(403, {"detail": "forbidden"})] * 6
    routes = ["GET /api/notifications/email", "PUT /api/notifications/email", "POST /api/notifications/email/test"]
    denied = await events("access.denied")
    assert [(e.actor_id, e.result_detail) for e in denied] == [
        (str(person.id), {"required": "owner", "route": route}) for person in (ada, auditor) for route in routes
    ]
    assert (await saved()).host is None
    assert [e for action in ("changed", "tested") for e in await events(f"notification_email.{action}")] == []

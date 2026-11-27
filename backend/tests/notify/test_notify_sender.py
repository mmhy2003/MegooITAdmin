import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from email import message_from_string

import pytest
from sqlalchemy import select, update

from alerts_helpers import make_alert, make_channel, make_rule, set_email
from app.alerts.models import AlertEvent
from app.core.config import Settings, get_settings
from app.core.db import SessionLocal
from app.notify import sender as sender_module
from app.notify import transports
from app.notify.crypto import seal
from app.notify.models import NotificationChannel, NotificationDelivery, NotificationEmail
from app.notify.sender import KEEP, MAX_ATTEMPTS, RETRY_DELAYS, Sender, email_recipients
from auth_helpers import add_grant, make_group, make_server, make_user
from conftest import owner_session
from sinks import HttpSink, SmtpSink

T0 = datetime(2026, 11, 26, 12, tzinfo=UTC)
pytestmark = pytest.mark.usefixtures("clean_alerts")


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def fake_clock() -> Clock:
    return Clock()


@pytest.fixture
def settings() -> Settings:
    return get_settings().model_copy(update={"webhook_allow_http": True})


@pytest.fixture
async def sink():
    async with HttpSink() as http:
        yield http


@pytest.fixture
async def server():
    group = await make_group("Production")
    return await make_server(group.id, "db-prod-01")


def make_sender(fake_clock, settings) -> Sender:
    return Sender(SessionLocal, settings=settings, clock=fake_clock)


async def deliveries() -> list[NotificationDelivery]:
    async with owner_session() as session:
        query = select(NotificationDelivery).order_by(NotificationDelivery.created_at, NotificationDelivery.id)
        return list((await session.scalars(query)).all())


async def undispatched() -> list[AlertEvent]:
    async with owner_session() as session:
        return list((await session.scalars(select(AlertEvent).where(AlertEvent.dispatched_at.is_(None)))).all())


async def test_dispatch_creates_one_delivery_per_matching_channel_by_severity(server, sink, fake_clock, settings):
    every = await make_channel("webhook_json", {"url": f"{sink.url}/every"})
    critical_only = await make_channel("webhook_slack", {"url": f"{sink.url}/critical"}, min_severity="critical")
    await make_channel("webhook_json", {"url": f"{sink.url}/off"}, enabled=False)
    warning = await make_alert(server.id, fired_at=T0, rule=await make_rule(name="Warn", severity="warning"))
    critical = await make_alert(server.id, fired_at=T0, rule=await make_rule(name="Crit"), instance="/var")
    sender = make_sender(fake_clock, settings)

    assert await sender.dispatch() == 2

    rows = await deliveries()
    pairs = {(row.event_id, row.channel_id) for row in rows}
    [warning_event], [critical_event] = await asyncio.gather(_event_ids(warning.id), _event_ids(critical.id))
    assert pairs == {(warning_event, every.id), (critical_event, every.id), (critical_event, critical_only.id)}
    assert all(row.state == "pending" and row.attempts == 0 and row.next_attempt_at == T0 for row in rows)
    assert await undispatched() == []

    assert await sender.send_due() == 3
    assert sorted(post["path"] for post in sink.received) == ["/critical", "/every", "/every"]
    slack = next(post for post in sink.received if post["path"] == "/critical")
    assert json.loads(slack["body"]) == {"text": "Critical: db-prod-01: /var is 93.4% full. Space used above 50%."}
    generic = [json.loads(post["body"]) for post in sink.received if post["path"] == "/every"]
    assert {body["alert"]["severity"] for body in generic} == {"warning", "critical"}
    assert all(row.state == "delivered" and row.delivered_at == T0 for row in await deliveries())


async def _event_ids(alert_id):
    async with owner_session() as session:
        return list((await session.scalars(select(AlertEvent.id).where(AlertEvent.alert_id == alert_id))).all())


async def test_email_goes_to_the_owner_and_the_group_admins_plus_extra_addresses_without_disabled_or_duplicates(
    server, fake_clock, settings
):
    other_group = await make_group("Staging")
    await make_user(email="owner@example.com")
    await make_user(email="gone-owner@example.com", disabled=True)
    await make_user(email="auditor@example.com", platform_role="auditor")
    for email, group_id, role, disabled in [
        ("admin@example.com", server.server_group_id, "admin", False),
        ("operator@example.com", server.server_group_id, "operator", False),
        ("elsewhere@example.com", other_group.id, "admin", False),
        ("gone-admin@example.com", server.server_group_id, "admin", True),
    ]:
        user, _ = await make_user(email=email, platform_role=None, disabled=disabled)
        await add_grant(user.id, group_id, role)
    extra = ["Pager@Example.com", "OWNER@example.com", "pager@example.com"]

    async with SmtpSink() as smtp:
        await set_email(
            enabled=True, host="127.0.0.1", port=smtp.port, security="none", from_address="alerts@example.com",
            extra_addresses=extra,
        )
        async with SessionLocal() as db:
            expected = ["admin@example.com", "owner@example.com", "pager@example.com"]
            assert await email_recipients(db, server.server_group_id) == expected

        await make_alert(server.id, fired_at=T0, rule=await make_rule())
        sender = make_sender(fake_clock, settings)
        await sender.dispatch()
        assert await sender.send_due() == 1

    [mail] = smtp.mail
    assert mail["from"] == "alerts@example.com"
    assert mail["to"] == expected
    assert message_from_string(mail["data"])["Subject"] == "[Critical] db-prod-01: / is 93.4% full"
    [row] = await deliveries()
    assert row.channel_id is None and row.state == "delivered"


async def test_email_matches_its_severity_and_unseals_its_password(server, fake_clock, settings):
    await set_email(
        enabled=True, host="127.0.0.1", port=1, security="none", from_address="alerts@example.com",
        min_severity="critical",
    )
    await make_alert(server.id, fired_at=T0, rule=await make_rule(severity="warning"))
    sender = make_sender(fake_clock, settings)
    await sender.dispatch()
    assert await deliveries() == []

    # A password sealed to another row does not open: the try fails without reaching the server.
    await set_email(min_severity="warning", username="alerts", password=None)
    async with owner_session() as session:
        await session.execute(update(NotificationEmail).values(password=seal("hunter2", b"another row")))
        await session.commit()
    await make_alert(server.id, fired_at=T0, rule=await make_rule(name="Crit"))
    await sender.dispatch()
    await sender.send_due()
    [row] = await deliveries()
    assert row.attempts == 1 and row.last_error == "undecryptable"


async def test_a_failed_try_is_retried_on_the_timetable_then_succeeds(server, sink, fake_clock, settings):
    await make_channel("webhook_json", {"url": f"{sink.url}/hook"})
    await make_alert(server.id, fired_at=T0, rule=await make_rule())
    sender = make_sender(fake_clock, settings)
    await sender.dispatch()
    sink.respond_with(500)

    assert await sender.send_due() == 1
    [row] = await deliveries()
    assert (row.state, row.attempts, row.last_error) == ("pending", 1, "http_status")
    assert row.next_attempt_at == T0 + timedelta(seconds=30)

    fake_clock.advance(seconds=29)
    assert await sender.send_due() == 0
    fake_clock.advance(seconds=1)
    assert await sender.send_due() == 1
    [row] = await deliveries()
    assert row.attempts == 2 and row.next_attempt_at == fake_clock.now + timedelta(seconds=120)

    sink.respond_with(204)
    fake_clock.advance(seconds=120)
    assert await sender.send_due() == 1
    [row] = await deliveries()
    assert (row.state, row.attempts, row.delivered_at) == ("delivered", 2, fake_clock.now)
    assert len(sink.received) == 3
    fake_clock.advance(days=1)
    assert await sender.send_due() == 0


async def test_after_six_tries_the_delivery_is_failed(server, sink, fake_clock, settings):
    await make_channel("webhook_json", {"url": f"{sink.url}/hook"})
    await make_alert(server.id, fired_at=T0, rule=await make_rule())
    sender = make_sender(fake_clock, settings)
    await sender.dispatch()
    sink.respond_with(503)

    for delay in (0, *RETRY_DELAYS):
        fake_clock.advance(seconds=delay)
        assert await sender.send_due() == 1

    [row] = await deliveries()
    assert (row.state, row.attempts, row.last_error) == ("failed", MAX_ATTEMPTS, "http_status")
    fake_clock.advance(days=1)
    assert await sender.send_due() == 0
    assert len(sink.received) == MAX_ATTEMPTS


async def test_an_event_older_than_an_hour_is_dispatched_without_deliveries(server, sink, fake_clock, settings):
    await make_channel("webhook_json", {"url": f"{sink.url}/hook"})
    rule = await make_rule()
    await make_alert(server.id, fired_at=T0 - timedelta(hours=1, seconds=1), rule=rule)
    await make_alert(server.id, fired_at=T0 - timedelta(minutes=59), rule=rule, instance="/var")

    assert await make_sender(fake_clock, settings).dispatch() == 2

    assert len(await deliveries()) == 1
    assert await undispatched() == []


async def test_no_channel_and_no_email_dispatches_with_no_deliveries(server, fake_clock, settings):
    await make_alert(server.id, fired_at=T0, rule=await make_rule())

    assert await make_sender(fake_clock, settings).dispatch() == 1

    assert await deliveries() == []
    assert await undispatched() == []


async def test_a_channel_created_later_gets_nothing_from_the_past(server, sink, fake_clock, settings):
    await make_alert(server.id, fired_at=T0, rule=await make_rule())
    sender = make_sender(fake_clock, settings)
    await sender.dispatch()

    await make_channel("webhook_json", {"url": f"{sink.url}/hook"})
    assert await sender.dispatch() == 0
    assert await sender.send_due() == 0
    assert await deliveries() == [] and sink.received == []


async def test_two_senders_never_send_twice(server, sink, fake_clock, settings):
    for name in ("one", "two", "three"):
        await make_channel("webhook_json", {"url": f"{sink.url}/{name}"})
    rule = await make_rule()
    for instance in ("/", "/var", "/home", "/srv"):
        await make_alert(server.id, fired_at=T0, rule=rule, instance=instance)
    first, second = make_sender(fake_clock, settings), make_sender(fake_clock, settings)

    dispatched = await asyncio.gather(first.dispatch(), second.dispatch())
    sent = await asyncio.gather(first.send_due(), second.send_due())

    assert sum(dispatched) == 4
    assert sum(sent) == 12
    assert len(await deliveries()) == 12
    posts = [(post["path"], json.loads(post["body"])["alert"]["instance"]) for post in sink.received]
    assert len(posts) == len(set(posts)) == 12


async def test_deliveries_older_than_30_days_are_deleted(server, sink, fake_clock, settings):
    await make_channel("webhook_json", {"url": f"{sink.url}/hook"})
    rule = await make_rule()
    sender = make_sender(fake_clock, settings)
    await make_alert(server.id, fired_at=T0, rule=rule)
    await sender.dispatch()
    fake_clock.advance(days=1)
    await make_alert(server.id, fired_at=fake_clock.now, rule=rule, instance="/var")
    await sender.dispatch()
    await sender.send_due()

    fake_clock.now = T0 + KEEP
    assert await sender.prune() == 0
    fake_clock.advance(seconds=1)
    assert await sender.prune() == 1

    [row] = await deliveries()
    assert row.created_at == T0 + timedelta(days=1)


async def test_last_error_holds_only_a_code(server, sink, fake_clock, settings, monkeypatch, unused_tcp_port):
    await make_channel("webhook_json", {"url": f"http://127.0.0.1:{unused_tcp_port}/hook/path-secret"})
    monkeypatch.setattr(transports, "TELEGRAM_API", sink.url)
    await make_channel("telegram", {"bot_token": "123456:secret-bot-token", "chat_id": "-100200"})
    misplaced = await make_channel("webhook_slack", {"url": f"{sink.url}/hook"})
    # A secret moved from another row does not open.
    other = await make_channel("webhook_slack", {"url": f"{sink.url}/other"}, enabled=False)
    async with owner_session() as session:
        query = update(NotificationChannel).where(NotificationChannel.id == misplaced.id).values(secret=other.secret)
        await session.execute(query)
        await session.commit()
    sink.respond_with(403)
    await make_alert(server.id, fired_at=T0, rule=await make_rule())
    sender = make_sender(fake_clock, settings)
    await sender.dispatch()

    assert await sender.send_due() == 3

    assert sorted(row.last_error for row in await deliveries()) == ["connection_failed", "http_status", "undecryptable"]
    assert [post["path"] for post in sink.received] == ["/bot123456:secret-bot-token/sendMessage"]


async def test_an_unexpected_error_counts_as_a_try_and_the_queue_goes_on(server, sink, fake_clock, settings, caplog):
    broken = await make_channel("webhook_json", {"address": f"{sink.url}/hook"})  # no "url": a KeyError
    await make_channel("webhook_json", {"url": f"{sink.url}/hook"})
    await make_alert(server.id, fired_at=T0, rule=await make_rule())
    sender = make_sender(fake_clock, settings)
    await sender.dispatch()

    with caplog.at_level(logging.ERROR, logger="app.notify.sender"):
        assert await sender.send_due() == 2

    by_channel = {row.channel_id: row for row in await deliveries()}
    failed = by_channel.pop(broken.id)
    [delivered] = by_channel.values()
    assert (failed.state, failed.attempts, failed.last_error) == ("pending", 1, "internal")
    assert failed.next_attempt_at == T0 + timedelta(seconds=RETRY_DELAYS[0])
    assert delivered.state == "delivered" and len(sink.received) == 1
    assert any(record.exc_info for record in caplog.records)


async def test_run_logs_a_failure_and_goes_on(fake_clock, settings, monkeypatch, caplog):
    sender = make_sender(fake_clock, settings)
    calls, done = [], asyncio.Event()

    async def dispatch():
        calls.append("dispatch")
        if len(calls) == 1:
            raise RuntimeError("the database went away")
        done.set()
        return 0

    monkeypatch.setattr(sender, "dispatch", dispatch)
    monkeypatch.setattr(sender_module, "EVERY", 0.01)
    with caplog.at_level(logging.ERROR, logger="app.notify.sender"):
        task = asyncio.create_task(sender.run())
        await asyncio.wait_for(done.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert len(calls) >= 2
    assert any(record.exc_info for record in caplog.records)

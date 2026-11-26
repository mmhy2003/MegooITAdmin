"""The alert book on the real database, as the collector's role: each transition is an alerts row, an alert_events row
and an audit event in one transaction; what the database refused waits for the next poll."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from app.alerts.models import Alert, AlertRule
from app.collector.alerts import book as book_module
from app.collector.alerts.book import AlertBook
from app.collector.alerts.engine import Engine
from app.collector.state import StatusBook
from app.inventory.models import Server
from app.metrics.samples import Reading, Sample
from alerts_helpers import alerts_of, events_of, make_rule
from auth_helpers import events, make_group, make_server
from conftest import owner_session

T0 = datetime.now(UTC).replace(microsecond=0)


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class FailingSessions:
    """The collector's sessions, but the next `failures` calls are refused as if the database were down."""

    def __init__(self, sessions) -> None:
        self.sessions, self.failures = sessions, 0

    def __call__(self):
        if self.failures > 0:
            self.failures -= 1
            raise OperationalError("connect", {}, OSError("the database is down"))
        return self.sessions()


async def monitored_server(name: str = "db-01") -> Server:
    """A Linux server with a pinned host key, which the collector monitors."""
    group = await make_group(f"{name}-group")
    server = await make_server(group.id, name)
    async with owner_session() as session:
        await session.execute(
            update(Server).where(Server.id == server.id).values(host_key="ssh-ed25519 AAAA", host_key_pinned_at=T0)
        )
        await session.commit()
        return (await session.execute(select(Server).where(Server.id == server.id))).scalar_one()


def disk(server: Server, at: datetime, value: float) -> Sample:
    return Sample(time=at, server_id=server.id, readings=(Reading(metric="disk.used_percent", instance="/", value=value),))


async def test_a_fire_writes_the_alert_its_event_and_alert_fired_by_the_collector(clean_alerts, collector_sessions):
    server = await monitored_server()
    rule = await make_rule(name="Disk full")
    book = AlertBook(collector_sessions)
    await book.poll([server], StatusBook(collector_sessions))

    await book.observe(disk(server, T0, 95.0), 1)

    [alert] = await alerts_of(server.id)
    assert (alert.state, alert.rule_id, alert.rule_name, alert.instance) == ("firing", rule.id, "Disk full", "/")
    assert (alert.metric, alert.comparison, alert.threshold, alert.duration_seconds, alert.severity) == (
        "disk.used_percent",
        "above",
        50.0,
        0,
        "critical",
    )
    assert (alert.fired_at, alert.resolved_at, alert.end_reason) == (T0, None, None)
    assert (alert.value, alert.last_value, alert.peak_value) == (95.0, 95.0, 95.0)
    [event] = await events_of(alert.id)
    assert (event.kind, event.at, event.dispatched_at) == ("fired", T0, None)
    [audit] = await events("alert.fired")
    assert (audit.actor_type, audit.actor_name) == ("system", "collector")
    assert (audit.target_type, audit.target_id, audit.target_name) == ("alert", str(alert.id), "Disk full")
    assert audit.context == {"server_id": str(server.id), "server_group_id": str(server.server_group_id)}
    assert audit.result_detail == {
        "server": "db-01",
        "rule_id": str(rule.id),
        "metric": "disk.used_percent",
        "instance": "/",
        "severity": "critical",
        "value": "95.00",
        "threshold": "50.00",
        "end_reason": None,
    }
    assert book.pending == 0


async def test_a_resolve_updates_the_row_and_records_alert_resolved(clean_alerts, collector_sessions):
    server = await monitored_server()
    await make_rule()
    book = AlertBook(collector_sessions)
    await book.poll([server], StatusBook(collector_sessions))
    await book.observe(disk(server, T0, 95.0), 1)

    await book.observe(disk(server, T0 + timedelta(seconds=5), 40.0), 1)

    [alert] = await alerts_of(server.id)
    assert (alert.state, alert.resolved_at, alert.end_reason) == ("resolved", T0 + timedelta(seconds=5), None)
    assert (alert.value, alert.last_value, alert.peak_value) == (95.0, 40.0, 95.0)
    assert [event.kind for event in await events_of(alert.id)] == ["fired", "resolved"]
    [audit] = await events("alert.resolved")
    assert (audit.target_id, audit.result_detail["value"]) == (str(alert.id), "40.00")


async def test_a_refused_write_is_retried_at_the_next_poll(clean_alerts, collector_sessions):
    server = await monitored_server()
    await make_rule()
    sessions = FailingSessions(collector_sessions)
    book = AlertBook(sessions)
    await book.poll([server], StatusBook(collector_sessions))

    sessions.failures = 1
    await book.observe(disk(server, T0, 95.0), 1)
    # The resolve waits behind the fire it follows.
    await book.observe(disk(server, T0 + timedelta(seconds=5), 40.0), 1)

    assert book.pending == 2
    assert await alerts_of(server.id) == []

    await book.poll([server], StatusBook(collector_sessions))

    assert book.pending == 0
    [alert] = await alerts_of(server.id)
    assert (alert.state, alert.fired_at, alert.resolved_at) == ("resolved", T0, T0 + timedelta(seconds=5))
    assert [event.kind for event in await events_of(alert.id)] == ["fired", "resolved"]
    [fired], [resolved] = await events("alert.fired"), await events("alert.resolved")
    assert fired.seq < resolved.seq


class BadSeverity(Engine):
    """An engine whose first fire carries a severity the database's check refuses."""

    def __init__(self) -> None:
        super().__init__()
        self.spoiled = False

    def observe(self, *args, **kwargs):
        transitions = super().observe(*args, **kwargs)
        if transitions and not self.spoiled:
            self.spoiled = True
            first = transitions[0]
            first.firing.snapshot = (*first.firing.snapshot[:4], "bogus")
        return transitions


async def test_a_write_the_database_can_never_take_is_dropped_and_does_not_block_the_next(
    clean_alerts, collector_sessions
):
    server = await monitored_server()
    await make_rule()
    book = AlertBook(collector_sessions, BadSeverity())
    await book.poll([server], StatusBook(collector_sessions))

    await book.observe(disk(server, T0, 95.0), 1)
    await book.observe(disk(server, T0 + timedelta(seconds=5), 40.0), 1)
    await book.observe(disk(server, T0 + timedelta(seconds=10), 96.0), 1)

    assert book.pending == 0
    [alert] = await alerts_of(server.id)
    assert (alert.state, alert.fired_at, alert.severity) == ("firing", T0 + timedelta(seconds=10), "critical")


async def test_a_bug_in_one_write_loses_only_that_one(clean_alerts, collector_sessions, monkeypatch):
    server = await monitored_server()
    await make_rule()
    book = AlertBook(collector_sessions)
    await book.poll([server], StatusBook(collector_sessions))
    real = book_module.alert_event
    calls = []

    def broken_once(transition):
        calls.append(transition)
        if len(calls) == 1:
            raise RuntimeError("a bug")
        return real(transition)

    monkeypatch.setattr(book_module, "alert_event", broken_once)
    two = Sample(
        time=T0,
        server_id=server.id,
        readings=(
            Reading(metric="disk.used_percent", instance="/", value=95.0),
            Reading(metric="disk.used_percent", instance="/var", value=96.0),
        ),
    )

    await book.observe(two, 1)

    assert book.pending == 0
    assert [alert.instance for alert in await alerts_of(server.id)] == ["/var"]


async def test_a_restart_loads_the_firing_alerts(clean_alerts, collector_sessions):
    server = await monitored_server()
    await make_rule()
    first = AlertBook(collector_sessions)
    await first.poll([server], StatusBook(collector_sessions))
    await first.observe(disk(server, T0, 95.0), 1)

    restarted = AlertBook(collector_sessions)
    await restarted.load()
    await restarted.poll([server], StatusBook(collector_sessions))
    await restarted.observe(disk(server, T0 + timedelta(seconds=5), 40.0), 1)

    [alert] = await alerts_of(server.id)
    assert (alert.state, alert.last_value) == ("resolved", 40.0)
    assert [event.kind for event in await events_of(alert.id)] == ["fired", "resolved"]


async def test_a_duplicate_firing_row_is_dropped(clean_alerts, collector_sessions):
    server = await monitored_server()
    rule = await make_rule()
    # Firing in the database, but not known to this book: it never loaded it.
    book = AlertBook(collector_sessions)
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
                instance="/",
                state="firing",
                fired_at=T0 - timedelta(minutes=5),
            )
        )
        await session.commit()
    await book.poll([server], StatusBook(collector_sessions))

    await book.observe(disk(server, T0, 95.0), 1)

    assert book.pending == 0
    [alert] = await alerts_of(server.id)
    assert alert.fired_at == T0 - timedelta(minutes=5)
    assert await events("alert.fired") == []


async def test_poll_reads_the_rules_and_ends_alerts_of_a_disabled_rule(clean_alerts, collector_sessions):
    server = await monitored_server()
    rule = await make_rule()
    clock = Clock(T0 + timedelta(seconds=10))
    book = AlertBook(collector_sessions, clock=clock)
    await book.poll([server], StatusBook(collector_sessions))
    await book.observe(disk(server, T0, 95.0), 1)
    async with owner_session() as session:
        await session.execute(update(AlertRule).where(AlertRule.id == rule.id).values(enabled=False))
        await session.commit()

    await book.poll([server], StatusBook(collector_sessions))

    [alert] = await alerts_of(server.id)
    assert (alert.state, alert.end_reason, alert.resolved_at) == ("ended", "rule_disabled", clock.now)
    assert [event.kind for event in await events_of(alert.id)] == ["fired", "ended"]
    [audit] = await events("alert.ended")
    assert audit.result_detail["end_reason"] == "rule_disabled"


async def test_poll_fires_an_unreachable_rule_from_the_status_since(clean_alerts, collector_sessions):
    server = await monitored_server()
    await make_rule(name="Gone", metric="unreachable", comparison=None, threshold=None, duration_seconds=60)
    status = StatusBook(collector_sessions)
    await status.set(server.id, "unreachable", "no_samples")
    clock = Clock(status.since(server.id) + timedelta(seconds=59))
    book = AlertBook(collector_sessions, clock=clock)

    await book.poll([server], status)
    assert await alerts_of(server.id) == []

    clock.now += timedelta(seconds=1)
    await book.poll([server], status)

    [alert] = await alerts_of(server.id)
    assert (alert.state, alert.metric, alert.instance, alert.fired_at, alert.value) == (
        "firing",
        "unreachable",
        "",
        clock.now,
        None,
    )
    [audit] = await events("alert.fired")
    assert (audit.result_detail["value"], audit.result_detail["threshold"]) == (None, None)


async def test_the_firing_values_are_written_at_most_once_a_minute(clean_alerts, collector_sessions):
    server = await monitored_server()
    await make_rule()
    clock = Clock(T0)
    book = AlertBook(collector_sessions, clock=clock)
    await book.poll([server], StatusBook(collector_sessions))
    await book.observe(disk(server, T0, 95.0), 1)

    async def values() -> tuple[float | None, float | None]:
        [alert] = await alerts_of(server.id)
        return alert.last_value, alert.peak_value

    clock.now = T0 + timedelta(seconds=5)
    await book.observe(disk(server, clock.now, 97.0), 1)
    await book.observe(disk(server, clock.now, 96.0), 1)
    await book.poll([server], StatusBook(collector_sessions))
    assert await values() == (95.0, 95.0)

    clock.now = T0 + timedelta(seconds=60)
    await book.poll([server], StatusBook(collector_sessions))
    assert await values() == (96.0, 97.0)

    await book.observe(disk(server, clock.now, 98.0), 1)
    clock.now = T0 + timedelta(seconds=110)
    await book.poll([server], StatusBook(collector_sessions))
    assert await values() == (96.0, 97.0)

    clock.now = T0 + timedelta(seconds=120)
    await book.poll([server], StatusBook(collector_sessions))
    assert await values() == (98.0, 98.0)
    assert [event.kind for event in await events_of((await alerts_of(server.id))[0].id)] == ["fired"]
    assert len(await events("alert.fired")) == 1


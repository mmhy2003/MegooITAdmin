"""The check runner: the timetable, the check loop, and the Recorder that writes an outcome's row and containers and
sends its numbers as metrics."""

import asyncio
import contextlib
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.checks.models import SeenContainer
from app.checks.store import read_checks, read_containers
from app.collector.checks.parse import (
    Cert,
    CertificatesResult,
    CheckResult,
    ContainersResult,
    LoginsResult,
    Outcome,
    Proc,
    ProcessesResult,
    ServicesResult,
    Source,
    Unit,
    UpdatesResult,
)
from app.collector.checks import Check
from app.collector.checks import runner as runner_module
from app.collector.checks.runner import Recorder, Timetable, run_check, run_checks, server_name
from app.collector.stream import Target
from app.collector.throttle import Throttle
from app.ssh.client import connect
from app.collector.writer import Writer
from auth_helpers import make_group, make_server
from collector_helpers import parts

pytestmark = pytest.mark.usefixtures("clean_auth")

DOWN_URL = "postgresql+asyncpg://x:y@127.0.0.1:1/down_test"
AT = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
LOGGER = "app.collector.checks.runner"
SERVICES = ServicesResult(total=40, running=30, failed=1, failed_units=(Unit(unit="cron.service", description="Cron"),))
FINGERPRINT = ":".join(["AB"] * 32)


@pytest.fixture
async def down_sessions():
    engine = create_async_engine(DOWN_URL, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _server_id() -> uuid.UUID:
    group = await make_group("Production")
    return (await make_server(group.id, "web-1")).id


def _recorder(sessions) -> tuple[Recorder, Writer]:
    publisher, writer, _ = parts(sessions)
    return Recorder(sessions, publisher, writer), writer


def _container(container_id: str, name: str) -> SeenContainer:
    return SeenContainer(
        container_id=container_id,
        name=name,
        image=f"{name}:latest",
        compose_project="shop",
        compose_service=name,
        state="running",
        status="Up 3 hours",
    )


def _containers(*seen: SeenContainer) -> ContainersResult:
    return ContainersResult(containers=seen, total=len(seen), running=len(seen), not_running=0)


def _readings(writer: Writer) -> set[tuple[str, str, float]]:
    return {(r.metric, r.instance, r.value) for sample in writer._buffer for r in sample.readings}


async def test_an_ok_services_outcome_writes_the_row_and_a_reading(collector_sessions):
    server_id = await _server_id()
    recorder, writer = _recorder(collector_sessions)
    await recorder.record(server_id, "services", Outcome("ok", SERVICES), AT)
    async with collector_sessions() as session:
        check = (await read_checks(session, server_id))["services"]
    assert (check.status, check.checked_at, check.data["failed"]) == ("ok", AT, 1)
    assert writer.pending == 1
    (sample,) = writer._buffer
    assert (sample.time, sample.server_id) == (AT, server_id)
    assert [(r.metric, r.value) for r in sample.readings] == [("services.failed", 1.0)]


async def test_no_reading_when_the_status_is_not_ok(collector_sessions):
    server_id = await _server_id()
    recorder, writer = _recorder(collector_sessions)
    await recorder.record(server_id, "services", Outcome("timeout"), AT)
    async with collector_sessions() as session:
        check = (await read_checks(session, server_id))["services"]
    assert (check.status, check.data) == ("timeout", None)
    assert writer.pending == 0


CERT = Cert(
    port=443,
    subject="CN=web",
    issuer="CN=ca",
    not_after=AT + timedelta(days=30, hours=1),
    fingerprint_sha256=FINGERPRINT,
)
PROC = Proc(pid=1, name="init", user="root", cpu_percent=1.0, memory_bytes=1024)


@pytest.mark.parametrize(
    ("kind", "result", "metrics"),
    [
        (
            "containers",
            _containers(_container("a" * 12, "web")),
            {("containers.running", "", 1.0), ("containers.not_running", "", 0.0)},
        ),
        ("services", SERVICES, {("services.failed", "", 1.0)}),
        (
            "logins",
            LoginsResult(failed_24h=7, top_sources=(Source(address="203.0.113.9", count=7),)),
            {("logins.failed_24h", "", 7.0)},
        ),
        (
            "updates",
            UpdatesResult(manager="apt", pending=4, security=2, reboot_required=True, lists_refreshed_at=None),
            {("updates.pending", "", 4.0), ("updates.security", "", 2.0), ("updates.reboot_required", "", 1.0)},
        ),
        (
            "certificates",
            CertificatesResult(certificates=(CERT,)),
            {("cert.days_left", "443", 30.0), ("cert.days_left", "", 30.0)},
        ),
        ("processes", ProcessesResult(by_cpu=(PROC,), by_memory=(PROC,)), set()),
    ],
)
async def test_readings_of_each_kind(collector_sessions, kind, result: CheckResult, metrics):
    server_id = await _server_id()
    recorder, writer = _recorder(collector_sessions)
    await recorder.record(server_id, kind, Outcome("ok", result), AT)
    assert _readings(writer) == metrics
    assert writer.pending == (1 if metrics else 0)


async def test_an_ok_containers_outcome_replaces_the_containers(collector_sessions):
    server_id = await _server_id()
    recorder, _ = _recorder(collector_sessions)
    await recorder.record(server_id, "containers", Outcome("ok", _containers(_container("a" * 12, "web"))), AT)
    later = AT + timedelta(seconds=30)
    await recorder.record(server_id, "containers", Outcome("ok", _containers(_container("b" * 12, "db"))), later)
    async with collector_sessions() as session:
        rows = await read_containers(session, server_id)
        check = (await read_checks(session, server_id))["containers"]
    assert [(row.name, row.last_seen_at) for row in rows] == [("db", later)]
    assert "containers" not in check.data
    assert check.data["running"] == 1


async def test_a_failed_containers_outcome_keeps_them(collector_sessions):
    server_id = await _server_id()
    recorder, _ = _recorder(collector_sessions)
    await recorder.record(server_id, "containers", Outcome("ok", _containers(_container("a" * 12, "web"))), AT)
    await recorder.record(server_id, "containers", Outcome("failed"), AT + timedelta(seconds=30))
    async with collector_sessions() as session:
        rows = await read_containers(session, server_id)
        check = (await read_checks(session, server_id))["containers"]
    assert [(row.name, row.last_seen_at) for row in rows] == [("web", AT)]
    assert check.status == "failed"


async def test_a_removed_server_is_ignored(collector_sessions, caplog):
    recorder, writer = _recorder(collector_sessions)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        await recorder.record(uuid.uuid4(), "services", Outcome("ok", SERVICES), AT)
    assert [r for r in caplog.records if r.name == LOGGER] == []


async def test_with_the_database_down_it_warns_once_and_still_buffers_the_reading(down_sessions, caplog):
    recorder, writer = _recorder(down_sessions)
    server_id = uuid.uuid4()
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        await recorder.record(server_id, "services", Outcome("ok", SERVICES), AT)
        await recorder.record(server_id, "services", Outcome("ok", SERVICES), AT + timedelta(seconds=60))
    warnings = [r for r in caplog.records if r.name == LOGGER]
    assert len(warnings) == 1
    assert str(server_id) in warnings[0].getMessage()
    assert writer.pending == 2


class Echo(CheckResult):
    lines: list[str]


def echo(lines: list[bytes]) -> Echo:
    return Echo(lines=[line.decode() for line in lines])


def _check(kind="services", every=1.0, timeout=5.0, script=b"echo '{\"status\":\"ok\"}'", parse=echo, **kw) -> Check:
    return Check(kind, every, timeout, script, parse, **kw)


class FakeClock:
    def __init__(self) -> None:
        self.now = [0.0]

    def __call__(self) -> float:
        return self.now[0]


def test_every_check_is_due_at_the_start():
    clock = FakeClock()
    timetable = Timetable([_check("a", 5), _check("b", 5)], first_delay=0, clock=clock)
    check, due = timetable.next()
    assert (check.kind, due) == ("a", 0.0)


def test_a_check_that_ran_is_due_again_after_its_interval():
    timetable = Timetable([_check("a", 5), _check("b", 5)], first_delay=0, clock=FakeClock())
    timetable.ran("a", 0)
    check, due = timetable.next()
    assert (check.kind, due) == ("b", 0.0)
    timetable.ran("b", 0)
    assert timetable.next()[0].kind == "a"


def test_a_short_interval_comes_back_first():
    timetable = Timetable([_check("a", 1), _check("b", 5)], first_delay=0, clock=FakeClock())
    timetable.ran("a", 0)
    timetable.ran("b", 0)
    check, due = timetable.next()
    assert (check.kind, due) == ("a", 1.0)


def test_the_first_round_starts_within_the_first_delay():
    for _ in range(20):
        timetable = Timetable([_check("a", 5)], first_delay=10, clock=FakeClock())
        assert 0 <= timetable.next()[1] <= 10


@pytest.mark.parametrize(
    ("address", "name"),
    [
        ("10.0.0.1", None),
        ("2001:db8::1", None),
        ("Web-01.Example.com", "web-01.example.com"),
        ("bad_name", None),
    ],
)
def test_server_name(address, name):
    assert server_name(address) == name


class FakeRecorder:
    def __init__(self) -> None:
        self.records: list[tuple[str, Outcome, float]] = []

    async def record(self, server_id, kind, outcome, at) -> None:
        self.records.append((kind, outcome, time.monotonic()))


def _target(fake_server) -> Target:
    return Target(uuid.uuid4(), fake_server.host, fake_server.port, "megoo", fake_server.host_key(), 1)


async def _run_for(seconds: float, fake_server, checks, recorder) -> None:
    target = _target(fake_server)
    async with connect(target.address, target.port, target.username, target.host_key) as conn:
        timetable = Timetable(checks, first_delay=0)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(run_checks(conn, target, timetable, recorder), seconds)


async def test_a_check_runs_when_due_and_not_before(fake_server):
    recorder = FakeRecorder()
    await _run_for(2.5, fake_server, [_check(every=1.0)], recorder)
    assert len(recorder.records) == 3
    assert all(outcome == Outcome("ok", Echo(lines=[])) for _, outcome, _ in recorder.records)
    times = [at for _, _, at in recorder.records]
    assert all(later - earlier >= 0.9 for earlier, later in zip(times, times[1:], strict=False))


class Span(CheckResult):
    start: float
    end: float


def span(lines: list[bytes]) -> Span:
    return Span(start=float(lines[0]), end=float(lines[1]))


async def test_checks_run_one_at_a_time(fake_server):
    script = b"echo '{\"status\":\"ok\"}'; date +%s.%N; sleep 1; date +%s.%N"
    recorder = FakeRecorder()
    checks = [_check("services", 60, script=script, parse=span), _check("logins", 60, script=script, parse=span)]
    await _run_for(3.5, fake_server, checks, recorder)
    assert [kind for kind, _, _ in recorder.records] == ["services", "logins"]
    first, second = (outcome.result for _, outcome, _ in recorder.records)
    assert isinstance(first, Span) and isinstance(second, Span)
    assert second.start >= first.end


async def _run_one(fake_server, check: Check, address: str) -> Outcome:
    async with connect(fake_server.host, fake_server.port, "megoo", fake_server.host_key()) as conn:
        return await run_check(conn, check, address)


async def test_a_timeout_gives_timeout(fake_server):
    started = time.monotonic()
    try:
        outcome = await _run_one(fake_server, _check(timeout=1, script=b"exec sleep 10"), "127.0.0.1")
    finally:
        # Closing the channel leaves the sleep running, and the script tests count leftover processes.
        fake_server.exec("pkill", "-u", "megoo", "-x", "sleep")
    assert outcome == Outcome("timeout")
    assert time.monotonic() - started < 3
    assert "sleep" not in fake_server.exec("ps", "-u", "megoo", "-o", "comm=").stdout.split()


async def test_certificates_gets_the_host_name(fake_server):
    check = _check("certificates", script=b"echo '{\"status\":\"ok\"}'; echo \"$1\"", server_name=True)
    named = await _run_one(fake_server, check, "fake.example.com")
    assert named == Outcome("ok", Echo(lines=["fake.example.com"]))
    unnamed = await _run_one(fake_server, check, "127.0.0.1")
    assert unnamed == Outcome("ok", Echo(lines=[""]))


async def test_an_exception_in_a_parser_gives_failed(fake_server, caplog, monkeypatch):
    def broken(lines: list[bytes]) -> CheckResult:
        raise KeyError("a bug")

    monkeypatch.setattr(runner_module, "_bugs", Throttle())
    check = _check(parse=broken)
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        first = await _run_one(fake_server, check, "127.0.0.1")
        second = await _run_one(fake_server, check, "127.0.0.1")
    assert (first, second) == (Outcome("failed"), Outcome("failed"))
    assert len([r for r in caplog.records if r.name == LOGGER]) == 1

"""The check runner: the Recorder writes an outcome's row and containers, and sends its numbers as metrics."""

import logging
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
from app.collector.checks.runner import Recorder
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

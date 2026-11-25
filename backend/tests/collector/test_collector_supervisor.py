"""The supervisor against the fake server: a stream per server that can be tried, none for one that cannot, a restart
when a server's row changes, a stop when it is removed, and the heartbeat and pending states of every poll."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import delete, func, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.collector.stream import MAX_SIGN_INS
from app.collector.supervisor import Supervisor
from app.collector.writer import Writer
from app.inventory.models import Server
from auth_helpers import make_group, make_server
from collector_helpers import FAST, eventually, metric_rows, parts, pinned_server, status_of
from conftest import owner_session

DOWN_URL = "postgresql+asyncpg://x:y@127.0.0.1:1/down_test"


def supervisor_of(sessions, tmp_path) -> tuple[Supervisor, Writer]:
    publisher, writer, status = parts(sessions)
    sup = Supervisor(
        sessions=sessions, publisher=publisher, writer=writer, status=status, timings=FAST, heartbeat=tmp_path / "hb"
    )
    return sup, writer


@asynccontextmanager
async def supervising(sup: Supervisor, writer: Writer) -> AsyncIterator[None]:
    """Runs the writer while inside; leaving stops every stream and the writer, and writes what is left."""
    task = asyncio.create_task(writer.run())
    try:
        yield
    finally:
        await sup.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await writer.flush()


async def as_owner(statement) -> None:
    async with owner_session() as session:
        await session.execute(statement)
        await session.commit()


def counted(call):
    return lambda: asyncio.to_thread(call)


async def test_a_new_server_starts_streaming_and_a_removed_one_stops(
    clean_auth, collector_sessions, fake_server, tmp_path
):
    server = await pinned_server(fake_server, "sup-1")
    sup, writer = supervisor_of(collector_sessions, tmp_path)

    async with supervising(sup, writer):
        await sup.poll()
        assert set(sup.targets) == {server.id}
        await eventually(lambda: metric_rows(server.id))

        await as_owner(delete(Server).where(Server.id == server.id))
        await sup.poll()

        assert sup.targets == {}
        assert sup.status.known(server.id) is None
        await eventually(counted(lambda: fake_server.loops() == 0), timeout=6)


async def test_three_servers_give_three_sign_ins_and_three_loops(clean_auth, collector_sessions, fake_server, tmp_path):
    servers = [await pinned_server(fake_server, f"sup-2-{n}") for n in range(3)]
    sup, writer = supervisor_of(collector_sessions, tmp_path)
    before = await asyncio.to_thread(fake_server.sign_ins)

    async with supervising(sup, writer):
        await sup.poll()
        assert set(sup.targets) == {server.id for server in servers}

        await eventually(counted(lambda: fake_server.sign_ins() - before >= 3))
        await eventually(counted(lambda: fake_server.loops() == 3))
        assert await asyncio.to_thread(fake_server.sign_ins) - before == 3


async def test_windows_unpinned_and_flagged_servers_are_not_monitored_without_a_sign_in(
    clean_auth, collector_sessions, fake_server, tmp_path
):
    windows = await pinned_server(fake_server, "sup-3-windows", os="windows")
    group = await make_group("sup-3-unpinned-group")
    unpinned = await make_server(group.id, "sup-3-unpinned", address=fake_server.host, port=fake_server.port)
    flagged = await pinned_server(fake_server, "sup-3-flagged")
    await as_owner(update(Server).where(Server.id == flagged.id).values(host_key_changed_at=func.now()))
    sup, writer = supervisor_of(collector_sessions, tmp_path)
    before = await asyncio.to_thread(fake_server.sign_ins)

    async with supervising(sup, writer):
        await sup.poll()

        assert await status_of(windows.id) == ("not_monitored", "not_an_ssh_server")
        assert await status_of(unpinned.id) == ("not_monitored", "host_key_not_pinned")
        assert await status_of(flagged.id) == ("not_monitored", "host_key_changed")
        await asyncio.sleep(2)
        assert await asyncio.to_thread(fake_server.sign_ins) == before
        assert sup.targets == {}


async def test_a_changed_interval_restarts_the_loop(clean_auth, collector_sessions, fake_server, tmp_path):
    server = await pinned_server(fake_server, "sup-4")
    sup, writer = supervisor_of(collector_sessions, tmp_path)

    async with supervising(sup, writer):
        await sup.poll()
        await eventually(lambda: metric_rows(server.id))
        before = await asyncio.to_thread(fake_server.sign_ins)

        await as_owner(update(Server).where(Server.id == server.id).values(metrics_interval_seconds=2))
        await sup.poll()

        assert sup.targets[server.id].interval == 2
        await eventually(counted(lambda: fake_server.sign_ins() == before + 1))
        await eventually(counted(lambda: fake_server.loops() == 1))
        await asyncio.sleep(1)
        assert await asyncio.to_thread(fake_server.sign_ins) == before + 1


async def test_poll_touches_the_heartbeat_and_retries_pending_states(
    clean_auth, collector_sessions, fake_server, tmp_path
):
    # An account the fake server refuses, so the stream writes nothing before its 3-second watchdog.
    server = await pinned_server(fake_server, "sup-5", username="megoo-unknown")
    sup, writer = supervisor_of(collector_sessions, tmp_path)
    engine = create_async_engine(DOWN_URL, poolclass=NullPool)
    try:
        sup.status.sessions = async_sessionmaker(engine, expire_on_commit=False)
        await sup.status.set(server.id, "unreachable", "no_samples")  # refused by the database: pending
    finally:
        await engine.dispose()
    sup.status.sessions = collector_sessions
    assert await status_of(server.id) is None
    assert not (tmp_path / "hb").exists()

    async with supervising(sup, writer):
        await sup.poll()

        assert (tmp_path / "hb").exists()
        assert await status_of(server.id) == ("unreachable", "no_samples")


async def test_sign_ins_are_limited_to_20(clean_auth, collector_sessions, fake_server, tmp_path):
    server = await pinned_server(fake_server, "sup-6")
    sup, writer = supervisor_of(collector_sessions, tmp_path)
    assert MAX_SIGN_INS == 20
    assert sup.sign_ins._value == 20

    async with supervising(sup, writer):
        await sup.poll()
        stream, _ = sup._streams[server.id]
        assert stream.sign_ins is sup.sign_ins

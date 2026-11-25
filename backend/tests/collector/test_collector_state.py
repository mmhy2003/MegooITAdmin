"""server_status as the collector writes it: once per change of state or reason, never raising, and what a database
outage kept back is written by retry()."""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.collector.state import StatusBook
from app.collector.throttle import Throttle
from app.inventory.models import ServerStatus
from auth_helpers import make_group, make_server
from collector_helpers import status_of
from conftest import owner_session

DOWN_URL = "postgresql+asyncpg://x:y@127.0.0.1:1/down_test"


async def a_server(name: str = "web-01") -> uuid.UUID:
    group = await make_group(f"{name}-group")
    return (await make_server(group.id, name)).id


async def row_of(server_id: uuid.UUID) -> ServerStatus:
    async with owner_session() as session:
        return (await session.execute(select(ServerStatus).where(ServerStatus.server_id == server_id))).scalar_one()


async def rows() -> int:
    async with owner_session() as session:
        return (await session.execute(text("SELECT count(*) FROM server_status"))).scalar_one()


@pytest.fixture
async def down_sessions():
    engine = create_async_engine(DOWN_URL, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_a_change_is_written_once_with_its_time(clean_auth, collector_sessions):
    server_id = await a_server()
    book = StatusBook(collector_sessions)

    await book.set(server_id, "unreachable", "no_samples")
    first = await row_of(server_id)
    await book.set(server_id, "unreachable", "no_samples")

    assert await rows() == 1
    assert (await row_of(server_id)).since == first.since
    assert (first.state, first.reason) == ("unreachable", "no_samples")
    assert book.known(server_id) == ("unreachable", "no_samples")


async def test_since_moves_only_when_the_state_or_reason_changes(clean_auth, collector_sessions):
    server_id = await a_server()
    book = StatusBook(collector_sessions)

    await book.set(server_id, "unreachable", "unreachable")
    first = await row_of(server_id)
    await book.set(server_id, "unreachable", "key_refused")
    by_reason = await row_of(server_id)
    # A second book that knows nothing writes the same value: the upsert's WHERE leaves the row alone.
    await StatusBook(collector_sessions).set(server_id, "unreachable", "key_refused")
    same = await row_of(server_id)
    await book.set(server_id, "reachable")
    by_state = await row_of(server_id)

    assert first.since < by_reason.since == same.since < by_state.since
    assert (by_state.state, by_state.reason) == ("reachable", None)


async def test_a_sample_time_is_written_with_the_change(clean_auth, collector_sessions):
    server_id = await a_server()
    book = StatusBook(collector_sessions)
    async with owner_session() as session:
        at = (await session.execute(text("SELECT now() - interval '1 minute'"))).scalar_one()

    await book.set(server_id, "reachable", last_sample_at=at)

    assert (await row_of(server_id)).last_sample_at == at


async def test_a_server_that_was_removed_is_forgotten_without_error(clean_auth, collector_sessions):
    book = StatusBook(collector_sessions)
    gone = uuid.uuid4()

    await book.set(gone, "reachable")

    assert book.known(gone) is None
    assert gone not in book.known_ids()
    assert await rows() == 0


async def test_with_the_database_down_the_change_waits_and_is_written_by_retry(
    clean_auth, collector_sessions, down_sessions, caplog
):
    server_id = await a_server()
    book = StatusBook(down_sessions)

    await book.set(server_id, "unreachable", "no_samples")
    await book.set(server_id, "unreachable", "no_samples")
    await book.retry()

    assert await status_of(server_id) is None
    assert book.known(server_id) is None
    assert len([r for r in caplog.records if r.name == "app.collector.state"]) == 1

    book.sessions = collector_sessions
    await book.retry()

    assert await status_of(server_id) == ("unreachable", "no_samples")
    assert book.known(server_id) == ("unreachable", "no_samples")


async def test_a_pending_change_is_dropped_when_the_known_value_comes_back(
    clean_auth, collector_sessions, down_sessions
):
    server_id = await a_server()
    book = StatusBook(collector_sessions)
    await book.set(server_id, "reachable")

    book.sessions = down_sessions
    await book.set(server_id, "unreachable", "no_samples")
    await book.set(server_id, "reachable")
    book.sessions = collector_sessions
    await book.retry()

    assert await status_of(server_id) == ("reachable", None)


async def test_load_reads_the_rows_so_a_restart_rewrites_nothing(clean_auth, collector_sessions):
    server_id = await a_server()
    await StatusBook(collector_sessions).set(server_id, "not_monitored", "host_key_changed")
    before = await row_of(server_id)

    restarted = StatusBook(collector_sessions)
    await restarted.load()
    restarted.sessions = None  # any write would now fail loudly
    await restarted.set(server_id, "not_monitored", "host_key_changed")

    assert restarted.known(server_id) == ("not_monitored", "host_key_changed")
    assert restarted.known_ids() == {server_id}
    assert (await row_of(server_id)).since == before.since


async def test_load_raises_when_the_database_is_down(down_sessions):
    with pytest.raises((OSError, SQLAlchemyError)):
        await StatusBook(down_sessions).load()


async def test_forget_drops_the_known_value(clean_auth, collector_sessions):
    server_id = await a_server()
    book = StatusBook(collector_sessions)
    await book.set(server_id, "reachable")

    book.forget(server_id)

    assert book.known(server_id) is None
    assert book.known_ids() == set()


def test_the_throttle_lets_one_through_per_period():
    now = [100.0]
    throttle = Throttle(every=60.0, clock=lambda: now[0])

    passed = [throttle(), throttle()]
    now[0] = 159.9
    passed.append(throttle())
    now[0] = 160.0
    passed += [throttle(), throttle()]

    assert passed == [True, False, False, True, False]

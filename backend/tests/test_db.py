import typing

import pytest
from sqlalchemy import text

from app.core.db import DbSession, SessionLocal, get_session

PROBE = "get_session_probe"


async def _probe_exists() -> bool:
    async with SessionLocal() as session:
        return (await session.execute(text(f"SELECT to_regclass('{PROBE}') IS NOT NULL"))).scalar_one()


@pytest.fixture(autouse=True)
async def no_probe_table():
    yield
    async with SessionLocal() as session:
        await session.execute(text(f"DROP TABLE IF EXISTS {PROBE}"))
        await session.commit()


async def test_a_session_runs_a_query_on_the_test_database():
    async with SessionLocal() as session:
        assert (await session.execute(text("SELECT 1"))).scalar_one() == 1


async def test_get_session_commits_after_the_handler():
    sessions = get_session()
    session = await anext(sessions)
    await session.execute(text(f"CREATE TABLE {PROBE} (id int)"))
    with pytest.raises(StopAsyncIteration):
        await anext(sessions)
    assert await _probe_exists()


async def test_get_session_rolls_back_when_the_handler_raises():
    sessions = get_session()
    session = await anext(sessions)
    await session.execute(text(f"CREATE TABLE {PROBE} (id int)"))
    with pytest.raises(RuntimeError):
        await sessions.athrow(RuntimeError("handler failed"))
    assert not await _probe_exists()


def test_db_session_closes_before_the_response():
    # The commit (and the audit guard) must run before the response is sent, so a failed commit answers 500.
    assert typing.get_args(DbSession)[1].scope == "function"

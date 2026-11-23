import typing

import pytest
from conftest import owner_session
from sqlalchemy import text

from app.core.db import DbSession, SessionLocal, get_session
from app.core.db_roles import API_ROLE

pytestmark = pytest.mark.usefixtures("database_at_head")

PROBE = "get_session_probe"


async def _probe_rows() -> int:
    async with SessionLocal() as session:
        return (await session.execute(text(f"SELECT count(*) FROM {PROBE}"))).scalar_one()


@pytest.fixture(autouse=True)
async def probe_table(database_at_head):
    # The API role cannot create tables, so the owner creates the probe and grants it.
    async with owner_session() as session:
        await session.execute(text(f"CREATE TABLE {PROBE} (id int)"))
        await session.execute(text(f"GRANT SELECT, INSERT ON {PROBE} TO {API_ROLE}"))
        await session.commit()
    yield
    async with owner_session() as session:
        await session.execute(text(f"DROP TABLE IF EXISTS {PROBE}"))
        await session.commit()


async def test_a_session_runs_a_query_on_the_test_database():
    async with SessionLocal() as session:
        assert (await session.execute(text("SELECT 1"))).scalar_one() == 1


async def test_get_session_commits_after_the_handler():
    sessions = get_session()
    session = await anext(sessions)
    await session.execute(text(f"INSERT INTO {PROBE} (id) VALUES (1)"))
    with pytest.raises(StopAsyncIteration):
        await anext(sessions)
    assert await _probe_rows() == 1


async def test_get_session_rolls_back_when_the_handler_raises():
    sessions = get_session()
    session = await anext(sessions)
    await session.execute(text(f"INSERT INTO {PROBE} (id) VALUES (1)"))
    with pytest.raises(RuntimeError):
        await sessions.athrow(RuntimeError("handler failed"))
    assert await _probe_rows() == 0


def test_db_session_closes_before_the_response():
    # The commit (and the audit guard) must run before the response is sent, so a failed commit answers 500.
    assert typing.get_args(DbSession)[1].scope == "function"

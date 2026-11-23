"""Points the app at the test database before any app module is imported.

`megoocolab-runner services run test -- uv run pytest` starts that database and sets TEST_DATABASE_URL.
"""

import os
from pathlib import Path

import pytest

RUN_TESTS = "megoocolab-runner services run test -- uv run pytest"
ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


# The marker of a set without a test database, and the only file a run with that marker collects.
ONLY = {"docker": "test_container.py", "stack": "test_stack.py"}


def _own_file(config: pytest.Config) -> str | None:
    return ONLY.get(config.getoption("markexpr"))


def pytest_configure(config: pytest.Config) -> None:
    if _own_file(config):
        return
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.exit(f"TEST_DATABASE_URL is not set. Run the suite as: {RUN_TESTS}", returncode=2)
    database = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not database.endswith("_test"):
        pytest.exit(f"Refusing to run against {database!r}: the test database name must end in _test.", returncode=2)
    os.environ["DATABASE_URL"] = url
    os.environ["DB_NULL_POOL"] = "true"


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    # The image and stack sets have no test database, so a `-m docker` or `-m stack` run collects only its own file.
    own_file = _own_file(config)
    if own_file and collection_path.is_file() and collection_path.name != own_file:
        return True
    return None


@pytest.fixture(scope="session")
def database_at_head():
    # Sync: Alembic's env.py runs its own event loop. Imported here: DATABASE_URL is set in pytest_configure.
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(ALEMBIC_INI)), "head")


@pytest.fixture
async def empty_audit_log(database_at_head):
    from sqlalchemy import text

    from app.core.db import SessionLocal

    # The triggers refuse DELETE, so they are switched off for this transaction only, as a superuser can.
    async with SessionLocal() as session:
        await session.execute(text("SET LOCAL session_replication_role = replica"))
        await session.execute(text("DELETE FROM audit_log"))
        await session.execute(
            text("UPDATE audit_chain_head SET seq = 0, hash = :zero, time = NULL"), {"zero": bytes(32)}
        )
        await session.commit()

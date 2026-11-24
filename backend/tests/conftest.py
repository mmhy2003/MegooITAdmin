"""Points the app at the test database before any app module is imported.

`megoocolab-runner services run test -- uv run pytest` starts that database and sets TEST_DATABASE_URL, the URL
the app serves with, and TEST_DATABASE_OWNER_URL, the owner's URL that Alembic migrates with.
"""

import os
import tempfile
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path

import pytest

RUN_TESTS = "megoocolab-runner services run test -- uv run pytest"
# The throwaway key of every test set. Never a real installation's key.
TEST_AUTH_SECRET_KEY = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


# The marker of a set without a test database, and the only file a run with that marker collects.
ONLY = {"docker": "test_container.py", "stack": "test_stack.py"}


def _own_file(config: pytest.Config) -> str | None:
    return ONLY.get(config.getoption("markexpr"))


def _test_url(name: str) -> str:
    url = os.environ.get(name)
    if not url:
        pytest.exit(f"{name} is not set. Run the suite as: {RUN_TESTS}", returncode=2)
    database = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not database.endswith("_test"):
        pytest.exit(
            f"Refusing to run against {database!r} ({name}): the test database name must end in _test.", returncode=2
        )
    return url


def pytest_configure(config: pytest.Config) -> None:
    if _own_file(config):
        return
    os.environ["DATABASE_URL"] = _test_url("TEST_DATABASE_URL")
    os.environ["DATABASE_OWNER_URL"] = _test_url("TEST_DATABASE_OWNER_URL")
    os.environ["DB_NULL_POOL"] = "true"
    os.environ["AUTH_SECRET_KEY"] = TEST_AUTH_SECRET_KEY
    # Each run makes its own platform key in a fresh directory, never the image's path.
    os.environ["SSH_KEY_FILE"] = str(Path(tempfile.mkdtemp(prefix="megooitadmin-ssh-")) / "id_ed25519")


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    # The image and stack sets have no test database, so a `-m docker` or `-m stack` run collects only its own file.
    own_file = _own_file(config)
    if own_file and collection_path.is_file() and collection_path.name != own_file:
        return True
    return None


@cache
def _owner_engine():
    # Imported here: DATABASE_OWNER_URL is set in pytest_configure.
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    return create_async_engine(os.environ["DATABASE_OWNER_URL"], poolclass=NullPool)


def owner_session():
    """A session as megooitadmin, the owner of the tables, for what the API role may not do."""
    from sqlalchemy.ext.asyncio import AsyncSession

    return AsyncSession(_owner_engine(), expire_on_commit=False)


def upgrade_to_head() -> None:
    """Migrates as the owner, then sets the API role's password, as the entrypoint does. Sync: Alembic's env.py
    runs its own event loop. A downgrade below 0003 drops the API role, so every way back to head goes through here."""
    from alembic import command
    from alembic.config import Config

    from app.core.db_roles import sync_api_role_password

    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    sync_api_role_password()


@pytest.fixture(scope="session")
def database_at_head():
    upgrade_to_head()


@pytest.fixture
async def empty_audit_log(database_at_head):
    from sqlalchemy import text

    # The triggers refuse DELETE, so the owner switches them off for this transaction only.
    async with owner_session() as session:
        await session.execute(text("SET LOCAL session_replication_role = replica"))
        await session.execute(text("DELETE FROM audit_log"))
        await session.execute(
            text("UPDATE audit_chain_head SET seq = 0, hash = :zero, time = NULL"), {"zero": bytes(32)}
        )
        await session.commit()


@pytest.fixture
async def clean_auth(empty_audit_log):
    from sqlalchemy import text

    # The owner deletes every account (their sessions, recovery codes, grants and invites cascade), every server
    # (its tags cascade) before the server groups that hold them, and the setup code.
    async with owner_session() as session:
        await session.execute(text("DELETE FROM auth_setup"))
        await session.execute(text("DELETE FROM users"))
        await session.execute(text("DELETE FROM servers"))
        await session.execute(text("DELETE FROM server_groups"))
        await session.commit()


@pytest.fixture(scope="session")
def fake_server():
    """The fake sshd of the test set, with this run's platform key authorized for its three accounts."""
    from fake_server import start

    return start()


class FakeClock:
    """The time auth code reads through app.auth.clock.now(). It moves only when a test advances it."""

    def __init__(self) -> None:
        self.now = datetime(2026, 11, 23, 12, 0, 5, tzinfo=UTC)

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr("app.auth.clock.now", lambda: fake.now)
    return fake


@pytest.fixture
async def api(clean_auth, clock):
    """An HTTP client for the real app, from a fixed client address, with no account and the fake clock."""
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    transport = ASGITransport(app=create_app(), client=("127.0.0.1", 50000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

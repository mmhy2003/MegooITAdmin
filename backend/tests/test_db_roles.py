"""The password step: `python -m app.core.db_roles` gives the API role LOGIN and the password of DATABASE_URL, and the
collector role LOGIN and the password of DATABASE_COLLECTOR_URL."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from conftest import ALEMBIC_INI, owner_session, upgrade_to_head
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.core.db_roles import (
    API_ROLE,
    COLLECTOR_ROLE,
    ApiRoleError,
    sync_api_role_password,
    sync_collector_role_password,
)

BACKEND = Path(__file__).resolve().parents[1]
# The API role's password in the test set of megoocolab.toml.
PASSWORD = "megooitadminapi"
# The collector role's password in the same set.
COLLECTOR_PASSWORD = "megooitadmincollector"


def _url(user: str, password: str) -> str:
    return make_url(os.environ["DATABASE_OWNER_URL"]).set(username=user, password=password).render_as_string(
        hide_password=False
    )


def _settings(database_url: str, database_collector_url: str | None = None) -> Settings:
    return Settings(
        database_url=database_url,
        database_owner_url=os.environ["DATABASE_OWNER_URL"],
        database_collector_url=database_collector_url,
    )


@pytest.fixture(autouse=True)
def restored_password(database_at_head):
    yield
    settings = _settings(_url(API_ROLE, PASSWORD), _url(COLLECTOR_ROLE, COLLECTOR_PASSWORD))
    sync_api_role_password(settings)
    sync_collector_role_password(settings)


def _login(password: str, role: str = API_ROLE) -> str:
    async def run():
        url = make_url(_url(role, password)).set(drivername="postgresql")
        connection = await asyncpg.connect(url.render_as_string(hide_password=False))
        try:
            return await connection.fetchval("SELECT current_user")
        finally:
            await connection.close()

    return asyncio.run(run())


def _stored_password() -> str:
    async def run():
        async with owner_session() as session:
            sql = text("SELECT rolpassword FROM pg_authid WHERE rolname = :role")
            return (await session.execute(sql, {"role": API_ROLE})).scalar_one()

    return asyncio.run(run())


def test_after_the_step_the_api_role_logs_in_with_the_password_of_database_url():
    sync_api_role_password(_settings(_url(API_ROLE, PASSWORD)))
    assert _login(PASSWORD) == API_ROLE


def test_a_changed_password_works_and_the_old_one_is_refused():
    sync_api_role_password(_settings(_url(API_ROLE, PASSWORD)))
    sync_api_role_password(_settings(_url(API_ROLE, "changedpassword2")))
    assert _login("changedpassword2") == API_ROLE
    with pytest.raises(asyncpg.InvalidPasswordError):
        _login(PASSWORD)


def test_a_database_url_with_another_user_is_refused():
    with pytest.raises(ApiRoleError, match="DATABASE_URL must connect as megooitadmin_api"):
        sync_api_role_password(_settings(os.environ["DATABASE_OWNER_URL"]))


@pytest.mark.parametrize("password", ["", "pässword", "tab\tbed"])
def test_a_password_that_is_missing_or_not_printable_ascii_is_refused(password):
    with pytest.raises(ApiRoleError, match="DATABASE_URL"):
        sync_api_role_password(_settings(_url(API_ROLE, password)))


def test_the_stored_password_is_a_scram_verifier():
    sync_api_role_password(_settings(_url(API_ROLE, PASSWORD)))
    assert _stored_password().startswith("SCRAM-SHA-256$4096:")


def test_without_the_role_the_step_says_to_run_the_migrations():
    command.downgrade(Config(str(ALEMBIC_INI)), "0002")
    try:
        with pytest.raises(ApiRoleError, match=r"alembic upgrade head"):
            sync_api_role_password(_settings(_url(API_ROLE, PASSWORD)))
    finally:
        upgrade_to_head()


def test_the_module_exits_1_and_never_prints_the_url():
    owner_url = os.environ["DATABASE_OWNER_URL"]
    result = subprocess.run(
        [sys.executable, "-m", "app.core.db_roles"],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": owner_url},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1
    assert "DATABASE_URL must connect as megooitadmin_api" in result.stderr
    for output in (result.stdout, result.stderr):
        assert owner_url not in output
        assert "@localhost" not in output


def test_after_the_step_the_collector_role_logs_in():
    settings = _settings(_url(API_ROLE, PASSWORD), _url(COLLECTOR_ROLE, COLLECTOR_PASSWORD))
    assert sync_collector_role_password(settings) is True
    assert _login(COLLECTOR_PASSWORD, role=COLLECTOR_ROLE) == COLLECTOR_ROLE


def test_a_collector_url_with_another_user_is_refused():
    settings = _settings(_url(API_ROLE, PASSWORD), os.environ["DATABASE_OWNER_URL"])
    with pytest.raises(ApiRoleError, match="DATABASE_COLLECTOR_URL must connect as megooitadmin_collector"):
        sync_collector_role_password(settings)


def test_without_the_collector_url_the_step_says_so_and_exits_0():
    env = {name: value for name, value in os.environ.items() if name != "DATABASE_COLLECTOR_URL"}
    result = subprocess.run(
        [sys.executable, "-m", "app.core.db_roles"], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert "DATABASE_COLLECTOR_URL is not set" in result.stdout

import asyncio
import configparser
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.db import SessionLocal

BACKEND = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND / "alembic.ini"
VERSIONS = BACKEND / "migrations" / "versions"
EXTENSIONS = {"timescaledb", "vector"}


def _config() -> Config:
    return Config(str(ALEMBIC_INI))


def _fetch(sql: str) -> list:
    # Alembic's env.py runs its own event loop, so these tests are sync and query through a short-lived one.
    async def run():
        async with SessionLocal() as session:
            return (await session.execute(text(sql))).all()

    return asyncio.run(run())


def _head() -> str:
    return ScriptDirectory.from_config(_config()).get_current_head()


def _extensions() -> set[str]:
    return {row[0] for row in _fetch("SELECT extname FROM pg_extension")}


@pytest.fixture(scope="session", autouse=True)
def migrated():
    command.upgrade(_config(), "head")


def test_upgrade_head_records_the_head_and_enables_the_extensions():
    assert [row[0] for row in _fetch("SELECT version_num FROM alembic_version")] == [_head()]
    assert EXTENSIONS <= _extensions()


def test_the_first_revision_goes_down_and_up_again():
    # Walk down to 0001, check its downgrade, and come back to head.
    command.downgrade(_config(), "0001")
    command.downgrade(_config(), "-1")
    assert not EXTENSIONS & _extensions()
    command.upgrade(_config(), "head")
    assert EXTENSIONS <= _extensions()
    assert [row[0] for row in _fetch("SELECT version_num FROM alembic_version")] == [_head()]


def test_revision_files_are_named_by_number_and_slug():
    parser = configparser.RawConfigParser()
    parser.read(ALEMBIC_INI)
    assert parser.get("alembic", "file_template") == "%%(rev)s_%%(slug)s"


def test_revisions_are_numbered_consecutively_from_0001():
    script = ScriptDirectory.from_config(_config())
    files = sorted(VERSIONS.glob("*.py"))
    assert files, "migrations/versions holds no revision"
    for position, path in enumerate(files, start=1):
        number = f"{position:04d}"
        assert re.fullmatch(rf"{number}_[a-z0-9_]+\.py", path.name), f"{path.name} should be {number}_<slug>.py"
        revision = script.get_revision(number)
        assert revision is not None, f"{path.name}: revision should be {number!r}"
        assert Path(revision.path).name == path.name
        expected_down = None if position == 1 else f"{position - 1:04d}"
        assert revision.down_revision == expected_down, f"{path.name}: down_revision should be {expected_down!r}"
    assert script.get_heads() == [f"{len(files):04d}"]


def test_audit_log_is_a_hypertable_on_time():
    rows = _fetch(
        "SELECT hypertable_name FROM timescaledb_information.hypertables WHERE hypertable_name = 'audit_log'"
    )
    assert [row[0] for row in rows] == ["audit_log"]
    dimensions = _fetch(
        "SELECT column_name FROM timescaledb_information.dimensions WHERE hypertable_name = 'audit_log'"
    )
    assert [row[0] for row in dimensions] == ["time"]


def test_0002_goes_down_and_up_again_with_an_empty_chain():
    command.downgrade(_config(), "0001")
    assert _fetch("SELECT to_regclass('audit_log'), to_regclass('audit_chain_head')") == [(None, None)]
    assert _fetch("SELECT proname FROM pg_proc WHERE proname = 'audit_refuse_change'") == []
    command.upgrade(_config(), "head")
    assert _fetch("SELECT id, seq, hash, time FROM audit_chain_head") == [(1, 0, bytes(32), None)]


def test_the_models_match_the_migrations():
    command.check(_config())

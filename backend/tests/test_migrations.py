import asyncio
import configparser
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from conftest import owner_session, upgrade_to_head
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

BACKEND = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND / "alembic.ini"
VERSIONS = BACKEND / "migrations" / "versions"
EXTENSIONS = {"timescaledb", "vector"}


def _config() -> Config:
    return Config(str(ALEMBIC_INI))


def _fetch(sql: str) -> list:
    # Alembic's env.py runs its own event loop, so these tests are sync and query through a short-lived one.
    async def run():
        async with owner_session() as session:
            return (await session.execute(text(sql))).all()

    return asyncio.run(run())


def _execute(sql: str) -> None:
    async def run():
        async with owner_session() as session:
            await session.execute(text(sql))
            await session.commit()

    asyncio.run(run())


def _head() -> str:
    return ScriptDirectory.from_config(_config()).get_current_head()


def _extensions() -> set[str]:
    return {row[0] for row in _fetch("SELECT extname FROM pg_extension")}


def _api_role() -> list:
    return _fetch("SELECT rolname, rolsuper FROM pg_roles WHERE rolname = 'megooitadmin_api'")


@pytest.fixture(scope="session", autouse=True)
def migrated():
    upgrade_to_head()


def test_upgrade_head_records_the_head_and_enables_the_extensions():
    assert [row[0] for row in _fetch("SELECT version_num FROM alembic_version")] == [_head()]
    assert EXTENSIONS <= _extensions()


def test_the_first_revision_goes_down_and_up_again():
    # Walk down to 0001, check its downgrade, and come back to head.
    command.downgrade(_config(), "0001")
    command.downgrade(_config(), "-1")
    assert not EXTENSIONS & _extensions()
    upgrade_to_head()
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
    upgrade_to_head()
    assert _fetch("SELECT id, seq, hash, time FROM audit_chain_head") == [(1, 0, bytes(32), None)]


def test_0003_goes_down_and_up_again_with_the_api_role_and_its_grants():
    command.downgrade(_config(), "0002")
    assert _api_role() == []
    upgrade_to_head()
    assert _api_role() == [("megooitadmin_api", False)]
    assert _fetch(
        "SELECT has_table_privilege('megooitadmin_api', 'audit_log', 'INSERT'),"
        " has_table_privilege('megooitadmin_api', 'audit_log', 'UPDATE'),"
        " has_table_privilege('megooitadmin_api', 'audit_chain_head', 'UPDATE')"
    ) == [(True, False, True)]


AUTH_TABLES = ("users", "auth_sessions", "recovery_codes", "auth_setup")


def _auth_tables() -> list:
    return _fetch(f"SELECT {', '.join(f'to_regclass({t!r})' for t in AUTH_TABLES)}")


def test_0004_goes_down_and_up_again_with_the_auth_tables():
    command.downgrade(_config(), "0003")
    assert _auth_tables() == [(None, None, None, None)]
    upgrade_to_head()
    assert _auth_tables() == [AUTH_TABLES]
    # Accounts are never deleted by the API; sessions and codes are.
    assert _fetch(
        "SELECT has_table_privilege('megooitadmin_api', 'users', 'DELETE'),"
        " has_table_privilege('megooitadmin_api', 'auth_sessions', 'DELETE')"
    ) == [(False, True)]


def _insert_user(email: str, extra: str = "", values: str = "") -> None:
    _execute(
        f"INSERT INTO users (id, email, name, password_hash, password_changed_at{extra})"
        f" VALUES (gen_random_uuid(), '{email}', 'Migration Probe', 'hash', now(){values})"
    )


def test_0005_goes_down_and_up_again_and_keeps_the_owner():
    command.downgrade(_config(), "0004")
    _insert_user("owner-0004@example.com", ", is_owner", ", true")
    _insert_user("other-0004@example.com", ", is_owner", ", false")
    try:
        upgrade_to_head()
        assert _fetch(
            "SELECT email, platform_role FROM users WHERE email LIKE '%-0004@example.com' ORDER BY email"
        ) == [("other-0004@example.com", None), ("owner-0004@example.com", "owner")]
        assert [row[0] for row in _fetch("SELECT key FROM roles ORDER BY position")] == [
            "owner",
            "admin",
            "operator",
            "auditor",
        ]
        command.downgrade(_config(), "0004")
        assert _fetch(
            "SELECT email, is_owner FROM users WHERE email LIKE '%-0004@example.com' ORDER BY email"
        ) == [("other-0004@example.com", False), ("owner-0004@example.com", True)]
    finally:
        upgrade_to_head()
        _execute("DELETE FROM users WHERE email LIKE '%-0004@example.com'")


def test_0005_downgrade_gives_an_invited_account_an_unusable_hash():
    _execute(
        "INSERT INTO users (id, email, name, password_changed_at)"
        " VALUES (gen_random_uuid(), 'invited-0005@example.com', 'Invited Probe', now())"
    )
    try:
        command.downgrade(_config(), "0004")
        assert _fetch("SELECT password_hash FROM users WHERE email = 'invited-0005@example.com'") == [("!",)]
    finally:
        upgrade_to_head()
        _execute("DELETE FROM users WHERE email = 'invited-0005@example.com'")


def test_an_operator_cannot_hold_manage_playbooks():
    _insert_user("operator-0005@example.com")
    _execute("INSERT INTO server_groups (id, name) VALUES (gen_random_uuid(), 'Migration probe group')")
    try:
        with pytest.raises(IntegrityError, match="role_grants_manage_playbooks_check"):
            _execute(
                "INSERT INTO role_grants (id, user_id, server_group_id, role, manage_playbooks)"
                " SELECT gen_random_uuid(), u.id, g.id, 'operator', true FROM users u, server_groups g"
                " WHERE u.email = 'operator-0005@example.com' AND g.name = 'Migration probe group'"
            )
    finally:
        _execute("DELETE FROM users WHERE email = 'operator-0005@example.com'")
        _execute("DELETE FROM server_groups WHERE name = 'Migration probe group'")


def test_0006_goes_down_and_up_again():
    command.downgrade(_config(), "0005")
    try:
        assert _fetch("SELECT to_regclass('servers'), to_regclass('server_tags')") == [(None, None)]
    finally:
        upgrade_to_head()
    assert _fetch("SELECT to_regclass('servers'), to_regclass('server_tags')") == [("servers", "server_tags")]


def _insert_probe_server(name: str, port: int) -> None:
    _execute(
        "INSERT INTO servers (id, server_group_id, name, address, port, os)"
        f" SELECT gen_random_uuid(), id, '{name}', '10.0.0.6', {port}, 'linux' FROM server_groups"
        " WHERE name = 'Migration probe group 0006'"
    )


def test_the_database_refuses_an_uppercase_tag_and_a_port_of_0():
    _execute("INSERT INTO server_groups (id, name) VALUES (gen_random_uuid(), 'Migration probe group 0006')")
    try:
        _insert_probe_server("probe-0006", 22)
        with pytest.raises(IntegrityError, match="server_tags_tag_check"):
            _execute("INSERT INTO server_tags (server_id, tag) SELECT id, 'Web' FROM servers WHERE name = 'probe-0006'")
        with pytest.raises(IntegrityError, match="servers_port_check"):
            _insert_probe_server("probe-0006-port", 0)
    finally:
        _execute("DELETE FROM servers WHERE name LIKE 'probe-0006%'")
        _execute("DELETE FROM server_groups WHERE name = 'Migration probe group 0006'")


HOST_KEY_COLUMNS = ["host_key_changed_at", "host_key_offered", "host_key_offered_at", "host_key_pinned_at"]


def _host_key_columns() -> list[str]:
    return [
        row[0]
        for row in _fetch(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'servers' AND column_name LIKE 'host_key_%' ORDER BY column_name"
        )
    ]


def test_0007_goes_down_and_up_again():
    command.downgrade(_config(), "0006")
    try:
        assert _host_key_columns() == []
    finally:
        upgrade_to_head()
    assert _host_key_columns() == HOST_KEY_COLUMNS


def test_the_database_refuses_a_pin_without_its_time_and_a_block_without_a_pin():
    _execute("INSERT INTO server_groups (id, name) VALUES (gen_random_uuid(), 'Migration probe group 0007')")
    try:
        _execute(
            "INSERT INTO servers (id, server_group_id, name, address, port, os)"
            " SELECT gen_random_uuid(), id, 'probe-0007', '10.0.0.7', 22, 'linux' FROM server_groups"
            " WHERE name = 'Migration probe group 0007'"
        )
        with pytest.raises(IntegrityError, match="servers_host_key_pinned_check"):
            _execute("UPDATE servers SET host_key = 'ssh-ed25519 AAAA' WHERE name = 'probe-0007'")
        with pytest.raises(IntegrityError, match="servers_host_key_changed_check"):
            _execute("UPDATE servers SET host_key_changed_at = now() WHERE name = 'probe-0007'")
    finally:
        _execute("DELETE FROM servers WHERE name = 'probe-0007'")
        _execute("DELETE FROM server_groups WHERE name = 'Migration probe group 0007'")


def test_the_models_match_the_migrations():
    command.check(_config())

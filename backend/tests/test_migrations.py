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


METRICS_RELATIONS = ("metrics", "metrics_1m", "metrics_1h")
# Policy jobs of the three relations. For a rollup, jobs.hypertable_name is its materialization hypertable.
METRICS_JOBS_SQL = (
    "SELECT j.job_id, j.proc_name, coalesce(c.view_name, j.hypertable_name) AS relation, j.schedule_interval, j.config"
    " FROM timescaledb_information.jobs j LEFT JOIN timescaledb_information.continuous_aggregates c"
    " ON c.materialization_hypertable_name = j.hypertable_name"
    " WHERE coalesce(c.view_name, j.hypertable_name) IN ('metrics', 'metrics_1m', 'metrics_1h')"
)
# (job, relation, config key, value, runs every or None when the default is fine)
METRICS_JOBS = [
    ("policy_retention", "metrics", "drop_after", "48 hours", "1 hour"),
    ("policy_compression", "metrics", "compress_after", "1 hour", None),
    ("policy_refresh_continuous_aggregate", "metrics_1m", "start_offset", "24 hours", "1 minute"),
    ("policy_compression", "metrics_1m", "compress_after", "2 days", None),
    ("policy_retention", "metrics_1m", "drop_after", "30 days", None),
    ("policy_refresh_continuous_aggregate", "metrics_1h", "start_offset", "7 days", "1 hour"),
    ("policy_compression", "metrics_1h", "compress_after", "30 days", None),
    ("policy_retention", "metrics_1h", "drop_after", "13 months", None),
]


def _metrics_relations() -> list:
    return _fetch(f"SELECT {', '.join(f'to_regclass({r!r})' for r in METRICS_RELATIONS)}")


def test_0008_goes_down_and_up_again():
    command.downgrade(_config(), "0007")
    try:
        assert _metrics_relations() == [(None, None, None)]
        assert _fetch(f"SELECT count(*) FROM ({METRICS_JOBS_SQL}) j") == [(0,)]
    finally:
        upgrade_to_head()
    assert _metrics_relations() == [METRICS_RELATIONS]


def test_metrics_is_a_hypertable_on_time_with_6_hour_chunks():
    assert _fetch(
        "SELECT column_name, time_interval = INTERVAL '6 hours' FROM timescaledb_information.dimensions"
        " WHERE hypertable_name = 'metrics'"
    ) == [("time", True)]


def test_both_rollups_are_real_time_with_their_chunk_intervals():
    rows = _fetch(
        "SELECT c.view_name, c.materialized_only, d.time_interval FROM timescaledb_information.continuous_aggregates c"
        " JOIN timescaledb_information.dimensions d ON d.hypertable_name = c.materialization_hypertable_name"
        " WHERE c.view_name IN ('metrics_1m', 'metrics_1h') ORDER BY c.view_name"
    )
    assert [(r[0], r[1]) for r in rows] == [("metrics_1h", False), ("metrics_1m", False)]
    assert _fetch(
        "SELECT d.time_interval = INTERVAL '30 days' FROM timescaledb_information.continuous_aggregates c"
        " JOIN timescaledb_information.dimensions d ON d.hypertable_name = c.materialization_hypertable_name"
        " WHERE c.view_name = 'metrics_1h'"
    ) == [(True,)]
    assert _fetch(
        "SELECT d.time_interval = INTERVAL '1 day' FROM timescaledb_information.continuous_aggregates c"
        " JOIN timescaledb_information.dimensions d ON d.hypertable_name = c.materialization_hypertable_name"
        " WHERE c.view_name = 'metrics_1m'"
    ) == [(True,)]


def test_the_metrics_jobs_are_scheduled():
    actual = sorted((row[1], row[2]) for row in _fetch(METRICS_JOBS_SQL))
    assert actual == sorted((job, relation) for job, relation, *_ in METRICS_JOBS)
    for job, relation, key, value, every in METRICS_JOBS:
        every_check = f", j.schedule_interval = INTERVAL '{every}'" if every else ""
        rows = _fetch(
            f"SELECT (j.config->>'{key}')::interval = INTERVAL '{value}'{every_check} FROM ({METRICS_JOBS_SQL}) j"
            f" WHERE j.proc_name = '{job}' AND j.relation = '{relation}'"
        )
        assert rows == [(True, True) if every else (True,)], (job, relation)


def _insert_metric(metric: str, value: str) -> None:
    _execute(
        "INSERT INTO metrics (time, server_id, metric, instance, value)"
        f" VALUES (now(), gen_random_uuid(), '{metric}', '', {value})"
    )


def test_the_database_refuses_a_bad_metric_name_and_a_value_that_is_not_finite():
    with pytest.raises(IntegrityError, match="metrics_metric_check"):
        _insert_metric("CPU.used", "1")
    with pytest.raises(IntegrityError, match="metrics_metric_check"):
        _insert_metric("a" * 65, "1")
    for bad in ("'NaN'::float8", "'Infinity'::float8", "'-Infinity'::float8"):
        with pytest.raises(IntegrityError, match="metrics_value_check"):
            _insert_metric("cpu.used_percent", bad)


def _collector_objects() -> list:
    return _fetch(
        "SELECT to_regclass('server_status'),"
        " EXISTS (SELECT FROM information_schema.columns"
        " WHERE table_name = 'servers' AND column_name = 'metrics_interval_seconds'),"
        " EXISTS (SELECT FROM pg_roles WHERE rolname = 'megooitadmin_collector')"
    )


def test_0009_goes_down_and_up_again():
    command.downgrade(_config(), "0008")
    try:
        assert _collector_objects() == [(None, False, False)]
    finally:
        upgrade_to_head()
    assert _collector_objects() == [("server_status", True, True)]


def test_the_database_refuses_an_interval_of_0_and_11_and_a_state_without_its_reason():
    _execute("INSERT INTO server_groups (id, name) VALUES (gen_random_uuid(), 'Migration probe group 0009')")
    try:
        _execute(
            "INSERT INTO servers (id, server_group_id, name, address, port, os)"
            " SELECT gen_random_uuid(), id, 'probe-0009', '10.0.0.9', 22, 'linux' FROM server_groups"
            " WHERE name = 'Migration probe group 0009'"
        )
        assert _fetch("SELECT metrics_interval_seconds FROM servers WHERE name = 'probe-0009'") == [(5,)]
        for bad in (0, 11):
            with pytest.raises(IntegrityError, match="servers_metrics_interval_seconds_check"):
                _execute(f"UPDATE servers SET metrics_interval_seconds = {bad} WHERE name = 'probe-0009'")
        with pytest.raises(IntegrityError, match="server_status_state_check"):
            _execute(
                "INSERT INTO server_status (server_id, state)"
                " SELECT id, 'unreachable' FROM servers WHERE name = 'probe-0009'"
            )
    finally:
        _execute("DELETE FROM servers WHERE name = 'probe-0009'")
        _execute("DELETE FROM server_groups WHERE name = 'Migration probe group 0009'")



def _checks_tables() -> list:
    return _fetch("SELECT to_regclass('server_checks'), to_regclass('containers')")


def test_0010_goes_down_and_up_again():
    command.downgrade(_config(), "0009")
    try:
        assert _checks_tables() == [(None, None)]
    finally:
        upgrade_to_head()
    assert _checks_tables() == [("server_checks", "containers")]


def test_the_database_refuses_a_bad_kind_status_runtime_and_state():
    _execute("INSERT INTO server_groups (id, name) VALUES (gen_random_uuid(), 'Migration probe group 0010')")
    try:
        _execute(
            "INSERT INTO servers (id, server_group_id, name, address, port, os)"
            " SELECT gen_random_uuid(), id, 'probe-0010', '10.0.0.10', 22, 'linux' FROM server_groups"
            " WHERE name = 'Migration probe group 0010'"
        )
        for constraint, kind, status, data in (
            ("server_checks_kind_check", "'x'", "'ok'", "NULL"),
            ("server_checks_status_check", "'services'", "'x'", "NULL"),
            ("server_checks_data_check", "'services'", "'ok'", "'{}'::jsonb"),
        ):
            with pytest.raises(IntegrityError, match=constraint):
                _execute(
                    "INSERT INTO server_checks (server_id, kind, status, checked_at, data)"
                    f" SELECT id, {kind}, {status}, now(), {data} FROM servers WHERE name = 'probe-0010'"
                )
        for constraint, runtime, state in (
            ("containers_runtime_check", "'podman'", "'running'"),
            ("containers_state_check", "'docker'", "'x'"),
        ):
            with pytest.raises(IntegrityError, match=constraint):
                _execute(
                    "INSERT INTO containers (server_id, runtime, container_id, name, image, state, status,"
                    " first_seen_at, last_seen_at)"
                    f" SELECT id, {runtime}, 'c0ffee', 'web', 'nginx', {state}, 'Up', now(), now()"
                    " FROM servers WHERE name = 'probe-0010'"
                )
    finally:
        _execute("DELETE FROM servers WHERE name = 'probe-0010'")
        _execute("DELETE FROM server_groups WHERE name = 'Migration probe group 0010'")


ALERT_TABLES = (
    "alert_rules",
    "alerts",
    "alert_events",
    "notification_channels",
    "notification_email",
    "notification_deliveries",
)


def _alert_tables() -> list:
    return _fetch(f"SELECT {', '.join(f'to_regclass({t!r})' for t in ALERT_TABLES)}")


def test_0011_goes_down_and_up_again():
    command.downgrade(_config(), "0010")
    try:
        assert _alert_tables() == [(None,) * len(ALERT_TABLES)]
        assert _fetch(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name = 'users' AND column_name = 'alerts_seen_at'"
        ) == [(0,)]
    finally:
        upgrade_to_head()
    assert _alert_tables() == [ALERT_TABLES]
    assert _fetch("SELECT id, enabled FROM notification_email") == [(1, False)]


def test_0011_inserts_the_four_starter_rules():
    command.downgrade(_config(), "0010")
    upgrade_to_head()
    assert _fetch(
        "SELECT name, metric, comparison, threshold, duration_seconds, severity, enabled,"
        " server_group_id IS NULL AND server_id IS NULL FROM alert_rules ORDER BY name"
    ) == [
        ("CPU busy", "cpu.used_percent", "above", 90.0, 900, "warning", True, True),
        ("Filesystem almost full", "disk.used_percent", "above", 90.0, 600, "critical", True, True),
        ("Memory almost full", "mem.used_percent", "above", 90.0, 600, "warning", True, True),
        ("Server unreachable", "unreachable", None, None, 300, "critical", True, True),
    ]


def _insert_rule(name: str, columns: str, values: str) -> None:
    _execute(
        f"INSERT INTO alert_rules (id, name, metric, duration_seconds, severity{columns})"
        f" VALUES (gen_random_uuid(), '{name}', {values})"
    )


def test_the_database_refuses_a_threshold_on_unreachable_and_two_scopes():
    _execute("INSERT INTO server_groups (id, name) VALUES (gen_random_uuid(), 'Migration probe group 0011')")
    try:
        _execute(
            "INSERT INTO servers (id, server_group_id, name, address, port, os)"
            " SELECT gen_random_uuid(), id, 'probe-0011', '10.0.0.11', 22, 'linux' FROM server_groups"
            " WHERE name = 'Migration probe group 0011'"
        )
        with pytest.raises(IntegrityError, match="alert_rules_condition_check"):
            _insert_rule(
                "probe-0011 threshold", ", comparison, threshold", "'unreachable', 300, 'critical', 'above', 1"
            )
        with pytest.raises(IntegrityError, match="alert_rules_condition_check"):
            _insert_rule("probe-0011 load", ", comparison, threshold", "'load.1m', 0, 'warning', 'above', 1001")
        with pytest.raises(IntegrityError, match="alert_rules_scope_check"):
            _execute(
                "INSERT INTO alert_rules (id, name, metric, duration_seconds, severity, server_group_id, server_id)"
                " SELECT gen_random_uuid(), 'probe-0011 scopes', 'unreachable', 300, 'critical', g.id, s.id"
                " FROM server_groups g, servers s WHERE s.name = 'probe-0011'"
                " AND g.name = 'Migration probe group 0011'"
            )
    finally:
        _execute("DELETE FROM alert_rules WHERE name LIKE 'probe-0011%'")
        _execute("DELETE FROM servers WHERE name = 'probe-0011'")
        _execute("DELETE FROM server_groups WHERE name = 'Migration probe group 0011'")


def _insert_alert(state: str) -> None:
    resolved_at = "NULL" if state == "firing" else "now()"
    _execute(
        "INSERT INTO alerts (id, server_id, rule_id, rule_name, metric, comparison, threshold, duration_seconds,"
        " severity, instance, state, fired_at, resolved_at)"
        " SELECT gen_random_uuid(), s.id, r.id, r.name, r.metric, r.comparison, r.threshold, r.duration_seconds,"
        f" r.severity, '/', '{state}', now(), {resolved_at}"
        " FROM servers s, alert_rules r WHERE s.name = 'probe-0011-alert' AND r.name = 'Filesystem almost full'"
    )


def test_one_firing_alert_per_rule_server_and_instance():
    _execute("INSERT INTO server_groups (id, name) VALUES (gen_random_uuid(), 'Migration probe group 0011 alerts')")
    try:
        _execute(
            "INSERT INTO servers (id, server_group_id, name, address, port, os)"
            " SELECT gen_random_uuid(), id, 'probe-0011-alert', '10.0.0.11', 22, 'linux' FROM server_groups"
            " WHERE name = 'Migration probe group 0011 alerts'"
        )
        _insert_alert("firing")
        with pytest.raises(IntegrityError, match="alerts_one_firing_key"):
            _insert_alert("firing")
        _insert_alert("resolved")
        assert _fetch(
            "SELECT a.state FROM alerts a JOIN servers s ON s.id = a.server_id"
            " WHERE s.name = 'probe-0011-alert' ORDER BY a.state"
        ) == [("firing",), ("resolved",)]
    finally:
        # The server's alerts cascade.
        _execute("DELETE FROM servers WHERE name = 'probe-0011-alert'")
        _execute("DELETE FROM server_groups WHERE name = 'Migration probe group 0011 alerts'")


def _logs_objects() -> list:
    return _fetch(
        "SELECT to_regclass('log_file_allowlist'), EXISTS (SELECT FROM pg_roles WHERE rolname = 'megooitadmin_logs')"
    )


def test_0012_goes_down_and_up_again():
    command.downgrade(_config(), "0011")
    try:
        assert _logs_objects() == [(None, False)]
    finally:
        upgrade_to_head()
    assert _logs_objects() == [("log_file_allowlist", True)]


def test_0012_gives_every_existing_group_the_starter_patterns():
    command.downgrade(_config(), "0011")
    try:
        _execute("INSERT INTO server_groups (id, name) VALUES (gen_random_uuid(), 'Migration probe group 0012')")
    finally:
        upgrade_to_head()
    try:
        assert _fetch(
            "SELECT a.pattern FROM log_file_allowlist a JOIN server_groups g ON g.id = a.server_group_id"
            " WHERE g.name = 'Migration probe group 0012' ORDER BY a.pattern"
        ) == [("/var/log/apache2/*.log",), ("/var/log/messages",), ("/var/log/nginx/*.log",), ("/var/log/syslog",)]
    finally:
        # Its patterns cascade.
        _execute("DELETE FROM server_groups WHERE name = 'Migration probe group 0012'")


def test_the_database_refuses_a_second_equal_pattern_in_a_group():
    _execute("INSERT INTO server_groups (id, name) VALUES (gen_random_uuid(), 'Migration probe group 0012 unique')")
    insert = (
        "INSERT INTO log_file_allowlist (id, server_group_id, pattern)"
        " SELECT gen_random_uuid(), id, '/var/log/app.log' FROM server_groups"
        " WHERE name = 'Migration probe group 0012 unique'"
    )
    try:
        _execute(insert)
        with pytest.raises(IntegrityError, match="log_file_allowlist_server_group_id_pattern_key"):
            _execute(insert)
    finally:
        _execute("DELETE FROM server_groups WHERE name = 'Migration probe group 0012 unique'")


def test_the_models_match_the_migrations():
    command.check(_config())

"""The API role megooitadmin_api and the collector role megooitadmin_collector have only the grants declared here.
A migration that creates a table grants the API role what the table needs, and adds the table to API_GRANTS (an empty
set keeps a table closed on purpose)."""

import pytest
from conftest import owner_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.core.db import Base
from app.core.db_roles import API_ROLE

pytestmark = pytest.mark.usefixtures("database_at_head")

INSUFFICIENT_PRIVILEGE = "42501"
API_GRANTS: dict[str, frozenset[str]] = {
    "audit_log": frozenset({"SELECT", "INSERT"}),
    "audit_chain_head": frozenset({"SELECT", "UPDATE"}),
    "users": frozenset({"SELECT", "INSERT", "UPDATE"}),
    "auth_sessions": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "recovery_codes": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "auth_setup": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "roles": frozenset({"SELECT"}),
    "server_groups": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "role_grants": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "user_invites": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "servers": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "server_tags": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # The backend only reads metrics. The collector's role writes them (MITA-26).
    "metrics": frozenset({"SELECT"}),
    "metrics_1m": frozenset({"SELECT"}),
    "metrics_1h": frozenset({"SELECT"}),
    # Written by the collector, read by the server API.
    "server_status": frozenset({"SELECT"}),
    "server_checks": frozenset({"SELECT"}),
    "containers": frozenset({"SELECT"}),
    # The Owner manages the rules. The collector writes alerts and their events; the sender marks an event dispatched.
    "alert_rules": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "alerts": frozenset({"SELECT"}),
    "alert_events": frozenset({"SELECT"}),
    "notification_channels": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    "notification_email": frozenset({"SELECT", "UPDATE"}),
    "notification_deliveries": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
}
# The sender claims an event FOR UPDATE and sets its dispatched_at, and changes nothing else of it.
API_COLUMN_GRANTS = {("alert_events", "dispatched_at", "UPDATE")}
COLLECTOR_ROLE = "megooitadmin_collector"
# The collector writes samples, its state table, the check results and the containers it finds, and flags a changed host key with its audit event.
COLLECTOR_GRANTS: dict[str, frozenset[str]] = {
    "metrics": frozenset({"INSERT"}),
    "servers": frozenset({"SELECT"}),
    "server_status": frozenset({"SELECT", "INSERT", "UPDATE"}),
    "audit_log": frozenset({"INSERT"}),
    "audit_chain_head": frozenset({"SELECT", "UPDATE"}),
    "server_checks": frozenset({"SELECT", "INSERT", "UPDATE"}),
    # Docker no longer lists a removed container: its row goes at the next check.
    "containers": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
    # It evaluates the rules, and writes alerts with their events. It never sees the channel tables.
    "alert_rules": frozenset({"SELECT"}),
    "alerts": frozenset({"SELECT", "INSERT", "UPDATE"}),
    "alert_events": frozenset({"INSERT"}),
}
COLLECTOR_COLUMN_GRANTS = {
    ("servers", column, "UPDATE") for column in ("host_key_changed_at", "host_key_offered", "host_key_offered_at")
}
ROLE_OID = "(SELECT oid FROM pg_roles WHERE rolname = :role)"
TABLE_GRANTS_SQL = (
    "SELECT c.relname, a.privilege_type FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
    f" CROSS JOIN LATERAL aclexplode(c.relacl) a WHERE n.nspname = 'public' AND a.grantee = {ROLE_OID}"
)
COLUMN_GRANTS_SQL = (
    "SELECT c.relname, a.attname, x.privilege_type FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid"
    " JOIN pg_namespace n ON n.oid = c.relnamespace CROSS JOIN LATERAL aclexplode(a.attacl) x"
    f" WHERE n.nspname = 'public' AND x.grantee = {ROLE_OID}"
)


async def _rows(sql: str, role: str = API_ROLE) -> list:
    async with owner_session() as session:
        return (await session.execute(text(sql), {"role": role})).all()


def _by_table(rows: list) -> dict[str, set[str]]:
    actual: dict[str, set[str]] = {}
    for table, privilege in rows:
        actual.setdefault(table, set()).add(privilege)
    return actual


async def test_the_api_role_is_not_a_superuser_and_cannot_create_roles_or_databases():
    rows = await _rows(
        "SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = :role"
    )
    assert rows == [(False, False, False, False, False)]


async def test_the_api_role_owns_no_relation():
    assert await _rows(f"SELECT relname FROM pg_class WHERE relowner = {ROLE_OID}") == []


async def test_the_api_role_cannot_create_a_table_in_public():
    async with owner_session() as session:
        await session.execute(text(f"SET LOCAL ROLE {API_ROLE}"))
        with pytest.raises(DBAPIError) as exc:
            await session.execute(text("CREATE TABLE api_role_probe (id int)"))
        await session.rollback()
    assert exc.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


async def test_the_api_role_cannot_insert_a_metric():
    async with owner_session() as session:
        await session.execute(text(f"SET LOCAL ROLE {API_ROLE}"))
        with pytest.raises(DBAPIError) as exc:
            await session.execute(
                text(
                    "INSERT INTO metrics (time, server_id, metric, value)"
                    " VALUES (now(), gen_random_uuid(), 'cpu.used_percent', 1)"
                )
            )
        await session.rollback()
    assert exc.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


async def test_the_api_roles_table_grants_are_the_declared_ones():
    actual = _by_table(await _rows(TABLE_GRANTS_SQL))
    assert actual == {t: set(p) for t, p in API_GRANTS.items() if p}, (
        f"{API_ROLE}'s grants differ from API_GRANTS: grant what a table needs in the migration that creates it, "
        "and declare it in API_GRANTS"
    )


def test_every_table_of_the_models_is_declared():
    missing = sorted(set(Base.metadata.tables) - set(API_GRANTS))
    assert missing == [], (
        f"{', '.join(missing)}: add the grant for {API_ROLE} to the table's migration, "
        "and the table to API_GRANTS in tests/security/test_db_privileges.py"
    )


async def test_the_collector_role_is_not_a_superuser_and_owns_nothing():
    rows = await _rows(
        "SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = :role",
        COLLECTOR_ROLE,
    )
    assert rows == [(False, False, False, False, False)]
    assert await _rows(f"SELECT relname FROM pg_class WHERE relowner = {ROLE_OID}", COLLECTOR_ROLE) == []


async def test_the_collector_roles_table_grants_are_the_declared_ones():
    actual = _by_table(await _rows(TABLE_GRANTS_SQL, COLLECTOR_ROLE))
    assert actual == {t: set(p) for t, p in COLLECTOR_GRANTS.items()}, (
        f"{COLLECTOR_ROLE}'s grants differ from COLLECTOR_GRANTS: grant only what the collector needs"
    )


async def test_the_column_grants_are_the_declared_ones():
    assert set(await _rows(COLUMN_GRANTS_SQL, COLLECTOR_ROLE)) == COLLECTOR_COLUMN_GRANTS
    assert set(await _rows(COLUMN_GRANTS_SQL)) == API_COLUMN_GRANTS


async def test_the_collector_role_can_insert_a_metric_and_cannot_read_users():
    async with owner_session() as session:
        await session.execute(text(f"SET LOCAL ROLE {COLLECTOR_ROLE}"))
        await session.execute(
            text(
                "INSERT INTO metrics (time, server_id, metric, value)"
                " VALUES (now(), gen_random_uuid(), 'cpu.used_percent', 1)"
            )
        )
        with pytest.raises(DBAPIError) as exc:
            await session.execute(text("SELECT 1 FROM users"))
        await session.rollback()
    assert exc.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


async def test_the_collector_role_may_flag_a_host_key_and_change_nothing_else_on_servers():
    async with owner_session() as session:
        group = (
            await session.execute(
                text(
                    "INSERT INTO server_groups (id, name)"
                    " VALUES (gen_random_uuid(), 'Collector probe group') RETURNING id"
                )
            )
        ).scalar_one()
        server = (
            await session.execute(
                text(
                    "INSERT INTO servers (id, server_group_id, name, address, port, os)"
                    " VALUES (gen_random_uuid(), :group, 'collector-probe', '10.0.0.26', 22, 'linux') RETURNING id"
                ),
                {"group": group},
            )
        ).scalar_one()
        await session.commit()
    try:
        async with owner_session() as session:
            await session.execute(text(f"SET LOCAL ROLE {COLLECTOR_ROLE}"))
            await session.execute(text("SELECT id FROM servers WHERE id = :id FOR UPDATE"), {"id": server})
            await session.execute(text("UPDATE servers SET host_key_offered = NULL WHERE id = :id"), {"id": server})
            with pytest.raises(DBAPIError) as exc:
                await session.execute(text("UPDATE servers SET name = 'x' WHERE id = :id"), {"id": server})
            await session.rollback()
        assert exc.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE
    finally:
        async with owner_session() as session:
            await session.execute(text("DELETE FROM servers WHERE id = :id"), {"id": server})
            await session.execute(text("DELETE FROM server_groups WHERE id = :id"), {"id": group})
            await session.commit()


async def test_the_api_role_can_read_server_status():
    async with owner_session() as session:
        await session.execute(text(f"SET LOCAL ROLE {API_ROLE}"))
        assert (await session.execute(text("SELECT count(*) FROM server_status"))).scalar_one() >= 0
        await session.rollback()


@pytest.mark.parametrize(
    "insert",
    [
        "INSERT INTO server_checks (server_id, kind, status, checked_at)"
        " VALUES (gen_random_uuid(), 'services', 'ok', now())",
        "INSERT INTO containers (server_id, runtime, container_id, name, image, state, status,"
        " first_seen_at, last_seen_at)"
        " VALUES (gen_random_uuid(), 'docker', 'c0ffee', 'web', 'nginx', 'running', 'Up', now(), now())",
    ],
    ids=["server_checks", "containers"],
)
async def test_the_api_role_cannot_write_checks_or_containers(insert: str):
    async with owner_session() as session:
        await session.execute(text(f"SET LOCAL ROLE {API_ROLE}"))
        with pytest.raises(DBAPIError) as exc:
            await session.execute(text(insert))
        await session.rollback()
    assert exc.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


@pytest.mark.parametrize("table", ["notification_channels", "notification_email", "notification_deliveries"])
async def test_the_collector_cannot_read_the_channel_tables(table: str):
    async with owner_session() as session:
        await session.execute(text(f"SET LOCAL ROLE {COLLECTOR_ROLE}"))
        with pytest.raises(DBAPIError) as exc:
            await session.execute(text(f"SELECT 1 FROM {table}"))
        await session.rollback()
    assert exc.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE

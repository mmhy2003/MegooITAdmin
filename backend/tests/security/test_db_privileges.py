"""The API role megooitadmin_api has only the grants declared here. A migration that creates a table grants the
role what the table needs, and adds the table to API_GRANTS (an empty set keeps a table closed on purpose)."""

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
}
ROLE_OID = "(SELECT oid FROM pg_roles WHERE rolname = :role)"


async def _rows(sql: str) -> list:
    async with owner_session() as session:
        return (await session.execute(text(sql), {"role": API_ROLE})).all()


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
    rows = await _rows(
        "SELECT c.relname, a.privilege_type FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
        f" CROSS JOIN LATERAL aclexplode(c.relacl) a WHERE n.nspname = 'public' AND a.grantee = {ROLE_OID}"
    )
    actual: dict[str, set[str]] = {}
    for table, privilege in rows:
        actual.setdefault(table, set()).add(privilege)
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

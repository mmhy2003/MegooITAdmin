"""The API role may not change the audit log, by privilege; the triggers refuse even the owner; and the chain check
finds what the owner changed or removed anyway."""

import pytest
from conftest import owner_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.audit import Actor, AuditEvent, Event, Problem, event_hash, record_alone, verify_chain
from app.audit.models import CHAINED_COLUMNS
from app.core.db import SessionLocal
from app.core.db_roles import API_ROLE

pytestmark = pytest.mark.usefixtures("empty_audit_log")

INSUFFICIENT_PRIVILEGE = "42501"
CHANGES = [
    "UPDATE audit_log SET reason = 'changed' WHERE seq = 3",
    "DELETE FROM audit_log WHERE seq = 3",
    "TRUNCATE audit_log",
]


@pytest.fixture
async def chain(empty_audit_log) -> list[AuditEvent]:
    return [
        await record_alone(Event(action="server.created", actor=Actor.human(7, "Alice"), reason=f"event {n}"))
        for n in range(1, 6)
    ]


async def tamper(sql: str, params: dict | None = None) -> None:
    """Runs the statement as the owner, with the triggers switched off."""
    async with owner_session() as session:
        await session.execute(text("SET LOCAL session_replication_role = replica"))
        await session.execute(text(sql), params or {})
        await session.commit()


async def check(**kw):
    async with SessionLocal() as session:
        return await verify_chain(session, **kw)


async def refused_for_the_owner(sql: str) -> str:
    async with owner_session() as session:
        with pytest.raises(DBAPIError) as exc:
            await session.execute(text(sql))
        await session.rollback()
    return str(exc.value)


async def refused_for_the_api_role(sql: str) -> str:
    async with SessionLocal() as session:
        with pytest.raises(DBAPIError) as exc:
            await session.execute(text(sql))
        await session.rollback()
    return exc.value.orig.sqlstate


async def audit_rows() -> int:
    async with owner_session() as session:
        return (await session.execute(text("SELECT count(*) FROM audit_log"))).scalar_one()


async def a_chunk() -> str:
    async with owner_session() as session:
        return (
            await session.execute(
                text(
                    "SELECT chunk_schema || '.' || chunk_name FROM timescaledb_information.chunks"
                    " WHERE hypertable_name = 'audit_log' LIMIT 1"
                )
            )
        ).scalar_one()


@pytest.fixture
async def triggers_off_for_the_api_role():
    async with owner_session() as session:
        await session.execute(text(f"ALTER ROLE {API_ROLE} SET session_replication_role = replica"))
        await session.commit()
    yield
    async with owner_session() as session:
        await session.execute(text(f"ALTER ROLE {API_ROLE} RESET session_replication_role"))
        await session.commit()


@pytest.mark.usefixtures("chain")
@pytest.mark.parametrize("sql", CHANGES)
async def test_the_api_role_may_not_change_audit_log(sql):
    assert await refused_for_the_api_role(sql) == INSUFFICIENT_PRIVILEGE


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM audit_chain_head",
        "TRUNCATE audit_chain_head",
        "INSERT INTO audit_chain_head (id, seq, hash) VALUES (2, 0, decode(repeat('00', 32), 'hex'))",
    ],
)
async def test_the_api_role_may_not_remove_or_add_a_chain_head(sql):
    assert await refused_for_the_api_role(sql) == INSUFFICIENT_PRIVILEGE


@pytest.mark.usefixtures("chain", "triggers_off_for_the_api_role")
@pytest.mark.parametrize("sql", CHANGES)
async def test_the_api_role_may_not_change_audit_log_with_the_triggers_off(sql):
    async with SessionLocal() as session:
        assert (await session.execute(text("SHOW session_replication_role"))).scalar_one() == "replica"
        with pytest.raises(DBAPIError) as exc:
            await session.execute(text(sql))
        await session.rollback()

    assert exc.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


@pytest.mark.usefixtures("chain")
async def test_the_api_role_cannot_switch_the_triggers_off():
    attempts = [
        "SET session_replication_role = replica",
        "ALTER TABLE audit_log DISABLE TRIGGER USER",
        "DROP TRIGGER audit_log_refuse_change ON audit_log",
        "CREATE OR REPLACE FUNCTION audit_refuse_change() RETURNS trigger LANGUAGE plpgsql"
        " AS $$ BEGIN RETURN OLD; END $$",
        "SELECT drop_chunks('audit_log', older_than => now() + INTERVAL '1 day')",
    ]

    for sql in attempts:
        assert await refused_for_the_api_role(sql) == INSUFFICIENT_PRIVILEGE, sql
    assert await audit_rows() == 5


@pytest.mark.usefixtures("chain")
async def test_the_api_role_may_not_change_a_chunk_of_audit_log():
    chunk = await a_chunk()

    for sql in [f"UPDATE {chunk} SET reason = 'changed'", f"DELETE FROM {chunk}", f"TRUNCATE {chunk}"]:
        assert await refused_for_the_api_role(sql) == INSUFFICIENT_PRIVILEGE, sql


@pytest.mark.usefixtures("chain")
async def test_a_chunk_takes_only_the_hypertables_grants():
    chunk = await a_chunk()
    privileges = ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"]
    columns = ", ".join(f"has_table_privilege(:role, :chunk, '{p}')" for p in privileges)

    async with owner_session() as session:
        row = (await session.execute(text(f"SELECT {columns}"), {"role": API_ROLE, "chunk": chunk})).one()

    assert tuple(row) == (True, True, False, False, False)


@pytest.mark.usefixtures("chain")
async def test_the_trigger_refuses_the_owner_an_update_on_audit_log():
    assert "append-only" in await refused_for_the_owner("UPDATE audit_log SET reason = 'changed' WHERE seq = 3")


@pytest.mark.usefixtures("chain")
async def test_the_trigger_refuses_the_owner_a_delete_on_audit_log():
    assert "append-only" in await refused_for_the_owner("DELETE FROM audit_log WHERE seq = 3")


@pytest.mark.usefixtures("chain")
async def test_the_trigger_refuses_the_owner_a_truncate_on_audit_log():
    assert "append-only" in await refused_for_the_owner("TRUNCATE audit_log")


async def test_the_trigger_refuses_the_owner_a_delete_on_the_chain_head():
    assert "append-only" in await refused_for_the_owner("DELETE FROM audit_chain_head")


async def test_the_trigger_refuses_the_owner_a_truncate_on_the_chain_head():
    assert "append-only" in await refused_for_the_owner("TRUNCATE audit_chain_head")


@pytest.mark.usefixtures("chain")
async def test_an_untouched_chain_passes():
    report = await check()

    assert (report.ok, report.checked, report.head_seq) == (True, 5, 5)
    assert (report.broken_at, report.problem) == (None, None)


async def test_an_empty_chain_passes():
    report = await check()

    assert (report.ok, report.checked, report.head_seq) == (True, 0, 0)


@pytest.mark.usefixtures("chain")
async def test_a_changed_field_gives_hash_mismatch_at_that_number():
    await tamper("UPDATE audit_log SET reason = 'changed' WHERE seq = 3")

    report = await check()

    assert (report.ok, report.problem, report.broken_at) == (False, Problem.HASH_MISMATCH, 3)


@pytest.mark.usefixtures("chain")
async def test_a_removed_middle_row_gives_missing_at_that_number():
    await tamper("DELETE FROM audit_log WHERE seq = 3")

    report = await check()

    assert (report.ok, report.problem, report.broken_at) == (False, Problem.MISSING, 3)


@pytest.mark.usefixtures("chain")
async def test_a_removed_newest_row_gives_head_mismatch():
    await tamper("DELETE FROM audit_log WHERE seq = 5")

    report = await check()

    assert (report.ok, report.problem) == (False, Problem.HEAD_MISMATCH)


async def test_a_row_rewritten_with_its_own_hash_gives_broken_link_at_the_next_number(chain):
    row = chain[2]
    columns = {c: getattr(row, c) for c in CHAINED_COLUMNS} | {"reason": "changed"}
    digest = event_hash(row.seq, row.time, row.prev_hash, columns)
    await tamper("UPDATE audit_log SET reason = 'changed', hash = :hash WHERE seq = 3", {"hash": digest})

    report = await check()

    assert (report.ok, report.problem, report.broken_at) == (False, Problem.BROKEN_LINK, 4)


@pytest.mark.usefixtures("chain")
async def test_a_changed_head_gives_head_mismatch():
    await tamper("UPDATE audit_chain_head SET hash = :x", {"x": b"\x01" * 32})

    report = await check()

    assert (report.ok, report.problem) == (False, Problem.HEAD_MISMATCH)


@pytest.mark.usefixtures("chain")
async def test_from_seq_starts_from_the_event_before():
    report = await check(from_seq=3)

    assert (report.ok, report.checked, report.head_seq) == (True, 3, 5)


@pytest.mark.usefixtures("chain")
async def test_from_seq_accepts_a_missing_start():
    await tamper("DELETE FROM audit_log WHERE seq IN (1, 2)")

    report = await check(from_seq=3)

    assert (report.ok, report.checked) == (True, 3)

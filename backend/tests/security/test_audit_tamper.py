"""The audit log refuses changes, and the chain check finds what a superuser changed or removed anyway."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.audit import Actor, AuditEvent, Event, Problem, event_hash, record_alone, verify_chain
from app.audit.models import CHAINED_COLUMNS
from app.core.db import SessionLocal

pytestmark = pytest.mark.usefixtures("empty_audit_log")


@pytest.fixture
async def chain(empty_audit_log) -> list[AuditEvent]:
    return [
        await record_alone(Event(action="server.created", actor=Actor.human(7, "Alice"), reason=f"event {n}"))
        for n in range(1, 6)
    ]


async def tamper(sql: str, params: dict | None = None) -> None:
    """Runs the statement with the triggers switched off, as a superuser can."""
    async with SessionLocal() as session:
        await session.execute(text("SET LOCAL session_replication_role = replica"))
        await session.execute(text(sql), params or {})
        await session.commit()


async def check(**kw):
    async with SessionLocal() as session:
        return await verify_chain(session, **kw)


async def refused(sql: str) -> str:
    async with SessionLocal() as session:
        with pytest.raises(DBAPIError) as exc:
            await session.execute(text(sql))
        await session.rollback()
    return str(exc.value)


@pytest.mark.usefixtures("chain")
async def test_update_on_audit_log_is_refused():
    assert "append-only" in await refused("UPDATE audit_log SET reason = 'changed' WHERE seq = 3")


@pytest.mark.usefixtures("chain")
async def test_delete_on_audit_log_is_refused():
    assert "append-only" in await refused("DELETE FROM audit_log WHERE seq = 3")


@pytest.mark.usefixtures("chain")
async def test_truncate_on_audit_log_is_refused():
    assert "append-only" in await refused("TRUNCATE audit_log")


async def test_delete_on_the_chain_head_is_refused():
    assert "append-only" in await refused("DELETE FROM audit_chain_head")


async def test_truncate_on_the_chain_head_is_refused():
    assert "append-only" in await refused("TRUNCATE audit_chain_head")


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

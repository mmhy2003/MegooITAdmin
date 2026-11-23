import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.audit import (
    GENESIS,
    Actor,
    AuditChainBusy,
    AuditChainHead,
    AuditEvent,
    Event,
    Person,
    Result,
    RiskClass,
    Source,
    Target,
    record,
    record_alone,
)
from app.audit import writer
from app.audit.models import CHAINED_COLUMNS
from app.core.db import SessionLocal

pytestmark = pytest.mark.usefixtures("empty_audit_log")


def sample(action: str = "server.created", **kw) -> Event:
    return Event(action=action, actor=Actor.human(7, "Alice"), **kw)


async def head() -> AuditChainHead:
    async with SessionLocal() as session:
        return (await session.execute(select(AuditChainHead))).scalar_one()


async def rows() -> list[AuditEvent]:
    async with SessionLocal() as session:
        return list((await session.execute(select(AuditEvent).order_by(AuditEvent.seq))).scalars())


async def test_the_first_event_has_number_1_and_the_zero_hash():
    async with SessionLocal() as session:
        first = await record(session, sample())
        await session.commit()

    assert first.seq == 1
    assert first.prev_hash == GENESIS


async def test_the_second_event_links_to_the_first():
    async with SessionLocal() as session:
        first = await record(session, sample())
        await session.commit()
    async with SessionLocal() as session:
        second = await record(session, sample("server.deleted"))
        await session.commit()

    assert second.seq == 2
    assert second.prev_hash == first.hash
    now = await head()
    assert (now.seq, now.hash, now.time) == (2, second.hash, second.time)


async def test_every_field_comes_back_as_written():
    event = Event(
        action="server.updated",
        actor=Actor.agent("s-1", "ops", "claude-opus-5-5"),
        result=Result.FAILURE,
        target=Target(type="server", id="42", name="db-01"),
        on_behalf_of=Person(id="7", name="Alice"),
        context={"agent_session": "s-1", "approval": "a-9"},
        source=Source(ip="2001:db8::1", user_agent="curl/8", auth_method="password", mfa=True),
        reason="resize the disk",
        change={"disk": {"before": 20, "after": 40}},
        result_detail={"exit_code": 1, "error": "no space"},
        risk_class=RiskClass.CHANGE,
    )
    async with SessionLocal() as session:
        await record(session, event)
        await session.commit()

    (row,) = await rows()
    expected = event.columns()
    for name in CHAINED_COLUMNS:
        value = getattr(row, name)
        assert (str(value) if name == "source_ip" else value) == expected[name], name
    assert row.time.microsecond % 1000 == 0
    assert row.time.utcoffset() == timedelta(0)


async def test_a_rolled_back_event_leaves_no_row_and_an_unchanged_head():
    async with SessionLocal() as session:
        await record(session, sample())
        await session.rollback()

    assert await rows() == []
    now = await head()
    assert (now.seq, now.hash, now.time) == (0, GENESIS, None)


async def test_the_next_event_after_a_rollback_takes_the_same_number():
    async with SessionLocal() as session:
        await record(session, sample())
        await session.rollback()
    async with SessionLocal() as session:
        row = await record(session, sample())
        await session.commit()

    assert row.seq == 1
    assert row.prev_hash == GENESIS


async def test_twenty_concurrent_writers_get_numbers_1_to_20():
    async def write() -> None:
        async with SessionLocal() as session:
            await record(session, sample())
            await session.commit()

    await asyncio.gather(*(write() for _ in range(20)))

    chain = await rows()
    assert [row.seq for row in chain] == list(range(1, 21))
    previous = GENESIS
    for row in chain:
        assert row.prev_hash == previous
        previous = row.hash


async def test_times_never_decrease_along_the_chain(monkeypatch):
    later = datetime.now(UTC)
    times = iter([later, later - timedelta(seconds=5)])

    class Backwards(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(times)

    monkeypatch.setattr(writer, "datetime", Backwards)
    async with SessionLocal() as session:
        first = await record(session, sample())
        second = await record(session, sample())
        await session.commit()

    assert second.time == first.time


async def test_record_alone_commits_although_the_caller_rolls_back():
    async with SessionLocal() as session:
        await record_alone(sample("auth.sign_in_failed"))
        await session.rollback()

    assert [row.action for row in await rows()] == ["auth.sign_in_failed"]


async def test_record_adds_the_action_to_session_info():
    async with SessionLocal() as session:
        await record(session, sample("server.created"))
        await record(session, sample("server.host_key_pinned"))

        assert session.info[writer.AUDIT_ACTIONS] == {"server.created", "server.host_key_pinned"}
        await session.rollback()


async def test_a_writer_that_cannot_get_the_head_lock_raises_audit_chain_busy(monkeypatch):
    monkeypatch.setattr(writer, "LOCK_TIMEOUT", "200ms")
    async with SessionLocal() as a, SessionLocal() as b:
        await record(a, sample())
        try:
            with pytest.raises(AuditChainBusy):
                await record(b, sample())
        finally:
            await b.rollback()
            await a.rollback()

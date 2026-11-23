"""The hash chain: each event has one canonical text form, and its hash covers that form and the previous hash."""

import hashlib
import ipaddress
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.events import check_json
from app.audit.models import CHAINED_COLUMNS, AuditChainHead, AuditEvent

GENESIS = bytes(32)


def time_text(time: datetime) -> str:
    """The time in UTC with milliseconds, for example 2026-11-23T07:45:31.362Z."""
    return time.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def document(seq: int, time: datetime, prev_hash: bytes, columns: Mapping[str, Any]) -> dict[str, Any]:
    """The event as it is hashed. A column without a value is left out, so a new nullable column does not change
    the hash of older events. Nulls inside JSON values stay."""
    doc: dict[str, Any] = {"seq": seq, "time": time_text(time), "prev_hash": prev_hash.hex()}
    for name, value in columns.items():
        if value is None:
            continue
        if name == "source_ip":
            # An IPv4Address from asyncpg and a str from the request give the same text.
            value = str(ipaddress.ip_interface(str(value)).ip)
        doc[name] = value
    return doc


def canonical(doc: Mapping[str, Any]) -> bytes:
    """The one byte form of a document: sorted keys, no spaces, UTF-8 text and no floats."""
    return json.dumps(
        check_json(dict(doc)), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def event_hash(seq: int, time: datetime, prev_hash: bytes, columns: Mapping[str, Any]) -> bytes:
    """The SHA-256 of the event's canonical form."""
    return hashlib.sha256(canonical(document(seq, time, prev_hash, columns))).digest()


class Problem(StrEnum):
    HASH_MISMATCH = "hash_mismatch"  # the stored hash is not the hash of the row's content: the row was changed
    BROKEN_LINK = "broken_link"  # prev_hash is not the hash of the event before: a row was replaced or re-hashed
    MISSING = "missing"  # a number is absent: a row was removed
    HEAD_MISMATCH = "head_mismatch"  # the newest row is not the one the head names


@dataclass(frozen=True)
class ChainReport:
    """The result of a chain check. When it fails, broken_at is the number of the first problem found."""

    ok: bool
    checked: int
    head_seq: int
    broken_at: int | None = None
    problem: Problem | None = None


BATCH = 1000


async def verify_chain(session: AsyncSession, *, from_seq: int = 1) -> ChainReport:
    """Checks the events from from_seq up to the head. The head is read first, so events written during the
    check do not disturb it. With from_seq above 1 the chain starts from the hash of the event before, or from
    the first event's own prev_hash when that event no longer exists."""
    head = (
        await session.execute(
            select(AuditChainHead).where(AuditChainHead.id == 1).execution_options(populate_existing=True)
        )
    ).scalar_one()
    if from_seq > head.seq:
        return ChainReport(ok=True, checked=0, head_seq=head.seq)
    if from_seq == 1:
        expected_prev: bytes | None = GENESIS
    else:
        expected_prev = (
            await session.execute(select(AuditEvent.hash).where(AuditEvent.seq == from_seq - 1))
        ).scalar_one_or_none()

    def fail(at: int, problem: Problem) -> ChainReport:
        return ChainReport(ok=False, checked=checked, head_seq=head.seq, broken_at=at, problem=problem)

    expected_seq, checked, last_hash = from_seq, 0, None
    while True:
        rows = (
            await session.execute(
                select(AuditEvent)
                .where(AuditEvent.seq >= expected_seq, AuditEvent.seq <= head.seq)
                .order_by(AuditEvent.seq)
                .limit(BATCH)
                .execution_options(populate_existing=True)
            )
        ).scalars().all()
        if not rows:
            break
        for row in rows:
            if row.seq != expected_seq:
                return fail(expected_seq, Problem.MISSING)
            if expected_prev is not None and row.prev_hash != expected_prev:
                return fail(row.seq, Problem.BROKEN_LINK)
            columns = {name: getattr(row, name) for name in CHAINED_COLUMNS}
            if event_hash(row.seq, row.time, row.prev_hash, columns) != row.hash:
                return fail(row.seq, Problem.HASH_MISMATCH)
            expected_prev = last_hash = row.hash
            expected_seq += 1
            checked += 1
    if expected_seq - 1 != head.seq or last_hash != head.hash:
        return fail(expected_seq - 1 if expected_seq > from_seq else head.seq, Problem.HEAD_MISMATCH)
    return ChainReport(ok=True, checked=checked, head_seq=head.seq)

"""The hash chain: each event has one canonical text form, and its hash covers that form and the previous hash."""

import hashlib
import ipaddress
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.audit.events import check_json

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
